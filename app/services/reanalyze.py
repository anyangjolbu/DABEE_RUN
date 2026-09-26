"""
미분석/LLM에러 monitor 레코드 일괄 재분석.

스크립트와 어드민 엔드포인트, 스케줄러가 모두 호출하는 단일 진입점.

STEP-3B-38: 무한 재시도 방지 cap (reanalyze_attempts < MAX_REANALYZE_ATTEMPTS).

STEP-COST-2:
- 확정 미분석(대상 미등장·LLM '관련없음')은 reanalyze_attempts=REANALYZE_FINAL로
  저장해 영구 제외. 같은 입력에 같은 답을 반복하던 호출 제거.
- 전역 원인 실패(Flex 429·예산·키 없음·인증/설정 오류·보류)와 타임아웃은 시도 횟수를
  올리지 않고 이번 회차 중단 → 원인이 풀리면 다음 사이클에 다시 시도.
  기사 단위 오류(error)만 +1, 연속 2회면 중단.
- 시간 한도(time_budget_sec): 스케줄러 루프를 오래 붙잡지 않도록.
- 최근 max_age_hours 이내 기사만 대상 (오래된 backlog가 예산을 잠식하지 않게).
- 일일 상한을 설정한 경우 그 REANALYZE_BUDGET_SHARE까지만 사용 (신규 기사 톤분류 몫 보존).
- 이미 텔레그램으로 나간 기사가 재분석에서 '비우호'가 되면 후속 알림 발송.
- 본문·description 모두 부족해 보류한 기사도 시도 횟수 +1. 예전에는 +1 없이 continue라
  같은 기사들이 ORDER BY id DESC LIMIT 큐 앞을 영구 점유할 수 있었다.
"""
import json
import logging
import time
from datetime import datetime, timedelta

from app import config
from app.core import repository
from app.core.db import get_conn
from app.core.repository import REANALYZE_FINAL
from app.services import llm_client, recipient_filter, telegram_sender
from app.services.crawler import fetch_body_full
from app.services.settings_store import load_settings
from app.services.tone_analyzer import analyze_tone

logger = logging.getLogger(__name__)

# 동일 기사를 재분석하는 최대 횟수 (초기 파이프라인 분석은 카운트 X)
MAX_REANALYZE_ATTEMPTS = 3
REANALYZE_MAX_AGE_HOURS = 72
REANALYZE_BUDGET_SHARE = 0.5
REANALYZE_TIME_BUDGET_SEC = 150

# 횟수를 올리지 않고 이번 회차를 중단하는 실패 (전역 원인·과금 없음·호출 안 함)
_STOP_STATUSES = llm_client.GLOBAL_FAILURES + ("deferred", "timeout")


def _bump_attempts(article_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE articles SET reanalyze_attempts = COALESCE(reanalyze_attempts, 0) + 1 "
            "WHERE id = ?",
            (article_id,),
        )


def _alert_hostile(row: dict, result: dict) -> None:
    """이미 발송된 기사가 재분석에서 비우호가 되면 monitor 수신자에게 후속 알림."""
    try:
        recipients = recipient_filter.match_recipients(
            article=row, recipients=repository.recipient_list_active(),
            track="monitor", tone=result,
        )
        if not recipients:
            return
        title = row.get("title_clean") or row.get("title") or ""
        press = row.get("press") or ""
        lines = ["🔴 비우호 재분류 (지연 분석)",
                 f"<{press}> {title}" if press else title,
                 row.get("original_url") or row.get("url") or ""]
        reason = result.get("reason") or ""
        if reason:
            lines.append(f"근거: {reason[:80]}")
        for s in (result.get("hostile_sentences") or [])[:1]:
            lines.append(f"  ㄴ {s[:60]}{'...' if len(s) > 60 else ''}")
        message = "\n".join(lines)
        for r in recipients:
            telegram_sender.send_to_chat(chat_id=r["chat_id"], message=message)
    except Exception as e:
        logger.warning(f"  ⚠️ 비우호 후속 알림 실패(무시): {e}")


def reanalyze_unanalyzed(limit: int = 50,
                         max_age_hours: float = REANALYZE_MAX_AGE_HOURS,
                         time_budget_sec: float = REANALYZE_TIME_BUDGET_SEC) -> dict:
    """
    track='monitor' AND tone_classification IN ('미분석','LLM에러')
    AND reanalyze_attempts < MAX_REANALYZE_ATTEMPTS
    AND 최근 max_age_hours 이내 수집 기사를 다시 톤 분석.

    Returns:
        {"target": N, "비우호": N, "양호": N, "미분석": N, "에러": N,
         "stopped": 중단 사유 또는 "", "items": [...]}
    """
    settings = load_settings()
    stats = {"비우호": 0, "양호": 0, "미분석": 0, "에러": 0}
    items: list[dict] = []
    stopped = ""
    cutoff = (datetime.now(config.KST) - timedelta(hours=max_age_hours)).isoformat()
    deadline = time.monotonic() + time_budget_sec

    with get_conn() as conn:
        rows = conn.execute("""
            SELECT id, url, original_url, title, title_clean, description, press,
                   theme_id, theme_label, matched_kw, reanalyze_attempts, sent_status
            FROM articles
            WHERE track='monitor'
              AND tone_classification IN ('미분석', 'LLM에러')
              AND COALESCE(reanalyze_attempts, 0) < ?
              AND collected_at >= ?
            ORDER BY id DESC
            LIMIT ?
        """, (MAX_REANALYZE_ATTEMPTS, cutoff, limit)).fetchall()

    target_n = len(rows)
    if target_n == 0:
        logger.info("🔄 재분석 대상 없음")
        return {"target": 0, **stats, "stopped": "", "items": []}

    logger.info(f"🔄 재분석 시작: {target_n}건 (limit={limit})")
    consecutive_errors = 0

    for r in rows:
        d = dict(r)
        if time.monotonic() > deadline:
            stopped = f"시간 한도 {time_budget_sec:.0f}초"
            break
        if llm_client.over_budget(settings, REANALYZE_BUDGET_SHARE):
            stopped = f"일일 예산의 {REANALYZE_BUDGET_SHARE:.0%} 도달 (신규 기사 톤분류 몫 보존)"
            break

        # 네이버 URL 1순위 (DB의 url) → 원문 fallback (original_url)
        naver_url = d["url"] or ""
        orig_url = d["original_url"] or ""
        try:
            body = ""
            if naver_url:
                body, _image = fetch_body_full(naver_url)
            if (not body or len(body) < 150) and orig_url and orig_url != naver_url:
                body2, _ = fetch_body_full(orig_url)
                if body2 and len(body2) >= 150:
                    body = body2
            # 3-Tier fallback: 본문 실패 시 description으로 재분석
            desc = d["description"] or ""
            if not body or len(body) < 150:
                if len(desc) >= 50:
                    logger.info(f"  📝 재분석 본문 부족({len(body)}자) → description({len(desc)}자) fallback")
                    body = desc
                else:
                    logger.info(f"  ⚠️ 본문·desc 모두 부족, 보류: {(naver_url or orig_url)[:60]}")
                    _bump_attempts(d["id"])
                    continue
            article = {
                "title":         d["title"],
                "description":   d["description"],
                "_crawled_body": body,
            }
            result = analyze_tone(article, d["theme_label"] or "", settings)

            status = result.get("llm_status") or ""
            if status in _STOP_STATUSES:
                stopped = f"LLM {status}"
                logger.info(f"  ⏸️ 재분석 중단({status}) — 원인이 풀리면 다음 사이클 재시도")
                break
            if status == "error":
                consecutive_errors += 1
            else:
                consecutive_errors = 0

            cls = result.get("classification", "미분석")
            stats[cls] = stats.get(cls, 0) + 1
            final = bool(result.get("final"))

            with get_conn() as conn:
                conn.execute("""
                    UPDATE articles
                       SET tone_classification = ?,
                           tone_reason         = ?,
                           tone_confidence     = ?,
                           tone_level          = ?,
                           tone_hostile        = ?,
                           tone_total          = ?,
                           tone_sentences      = ?,
                           reanalyze_attempts  = CASE WHEN ? THEN ?
                                                      ELSE COALESCE(reanalyze_attempts, 0) + 1 END
                     WHERE id = ?
                """, (
                    cls,
                    result.get("reason"),
                    result.get("confidence") or None,
                    result.get("level"),
                    int(result.get("hostile_count", 0) or 0),
                    int(result.get("total_count", 0) or 0),
                    json.dumps(result.get("hostile_sentences", []), ensure_ascii=False),
                    1 if final else 0, REANALYZE_FINAL,
                    d["id"],
                ))

            if cls == "비우호" and d.get("sent_status") == 1:
                _alert_hostile(d, result)

            items.append({
                "id":             d["id"],
                "title":          d["title_clean"],
                "classification": cls,
                "confidence":     result.get("confidence"),
            })
            if consecutive_errors >= 2:
                stopped = "LLM 오류 연속 2회"
                break
        except Exception as e:
            stats["에러"] += 1
            logger.error(f"  ❌ id={d['id']} 재분석 실패: {e}")
            # 크롤러/네트워크 예외도 cap 정책 적용 — 같은 기사 무한 재시도 방지
            try:
                _bump_attempts(d["id"])
            except Exception:
                pass
            items.append({
                "id":             d["id"],
                "title":          d["title_clean"],
                "classification": "에러",
                "error":          str(e)[:100],
            })

    logger.info(
        f"✅ 재분석 완료: 양호 {stats['양호']} / 비우호 {stats['비우호']} / "
        f"미분석 {stats['미분석']} / 에러 {stats['에러']}"
        + (f" | 중단: {stopped}" if stopped else "")
    )
    return {"target": target_n, **stats, "stopped": stopped, "items": items}
