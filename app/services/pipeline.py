"""
파이프라인 오케스트레이터.

STEP 4A-1:
- 테마별 track ('monitor' | 'reference')에 따라 분기
- monitor: 본문크롤링 → 톤분류 → DB저장 → 텔레그램(권한 매칭)
- reference: 본문크롤링 X, 톤분류 X, DB저장만 + 텔레그램은 reference 권한자만

STEP-COST-2:
- 요약은 LLM 없이 description (summarizer)
- 톤분류는 사이클당 LLM 시간 한도(TONE_TIME_BUDGET_SEC) 안에서만 호출.
  초과분은 '미분석'으로 저장·발송하고 재분석이 나중에 채운다.
- 기사 단위 예외 격리: 크롤링·톤분류·발송 중 어떤 예외가 나도
  저장과 발송은 계속 진행하고 다음 기사로 넘어간다 (기사 누락 방지).
- LLM 전역 장애(키 없음·인증/설정 오류·상한·Flex+Standard 모두 429)가 한 번 나면
  그 사이클의 나머지 기사는 LLM을 건너뛴다 (기사마다 대기하며 사이클이 늘어지지 않게).
- 재발송(resend_pending): 최근 RESEND_WINDOW_HOURS 동안 발송 전·실패로 남은 기사를
  아직 성공하지 못한 수신자에게 다시 보낸다 (텔레그램 429·저장 후 중단 대비).
"""

import json
import logging
import re
import time
from typing import Optional

from datetime import datetime, timedelta

from app import config
from app.core import repository
from app.services import (
    llm_client,
    crawler,
    naver_api,
    press_resolver,
    recipient_filter,
    relevance,
    settings_store,
    summarizer,
    telegram_sender,
    tone_analyzer,
)

logger = logging.getLogger(__name__)


# STEP-3B-11: reference → monitor 승격 트리거 키워드
# 본문에 이 중 하나라도 등장하면 reference도 톤 분석 진행
PROMOTE_KEYWORDS = ("SK하이닉스", "하이닉스", "SKhynix", "hynix",
                    "솔리다임", "곽노정", "최태원")

# STEP-COST-2: 사이클 시작부터 이 시간(벽시계, 크롤링·발송 포함)이 지나면 남은 기사는
# 톤분류 LLM을 건너뛰고 미분석으로 저장·발송 → 재분석이 채운다. 스케줄러 워치독 900초 대비 여유.
TONE_TIME_BUDGET_SEC = 480

# 재발송: 최근 이 시간 안의 기사만, 수집 직후 기사는 제외(진행 중 사이클과 겹치지 않게),
# (기사, 수신자)별 실패 누적 상한, 사이클당 최대 건수
RESEND_WINDOW_HOURS = 6
RESEND_MIN_AGE_MIN  = 3
RESEND_MAX_FAILS    = 5
RESEND_MAX_ARTICLES = 30


def _body_has_priority_target(body: str, title: str = "", description: str = "") -> bool:
    """본문/제목/설명 어디든 핵심 모니터링 대상이 등장하는지 확인.

    STEP-3B-36: 본문 크롤링 실패(빈 body) 또는 셀렉터 매칭 실패로 본문이
    부족한 경우에도 제목·description fallback으로 PROMOTE 키워드 검사.
    """
    haystack = " ".join(filter(None, [body or "", title or "", description or ""])).lower()
    if not haystack.strip():
        return False
    for kw in PROMOTE_KEYWORDS:
        if kw.lower() in haystack:
            return True
    return False


def _crawl(article: dict) -> str:
    """네이버 URL 1순위 → 부족 시 원문 URL fallback. 본문을 article에 기록하고 반환."""
    naver_url = article.get("link", "")
    orig_url = article.get("originallink", "")
    body, image_url = ("", "")
    if naver_url:
        body, image_url = crawler.fetch_body_full(naver_url)
    if (not body or len(body) < 150) and orig_url and orig_url != naver_url:
        logger.info(f"  🔁 네이버 본문 부족 → 원문 재시도: {orig_url[:60]}")
        body2, image_url2 = crawler.fetch_body_full(orig_url)
        if body2 and len(body2) >= 150:
            body = body2
        if not image_url:
            image_url = image_url2
    if body:
        article["_crawled_body"] = body
    if image_url:
        article["image_url"] = image_url
    return body or ""


def _analyze_monitor(article: dict, body: str, theme_label: str,
                     settings: dict, allow_llm: bool) -> dict:
    """monitor 기사 톤분류. 3-Tier: 본문 → description → 보류."""
    if not body or len(body) < 150:
        desc = article.get("description", "") or ""
        if len(desc) >= 50:
            logger.info(f"  📝 본문 부족({len(body)}자) → description({len(desc)}자) fallback: {article.get('press','?')}")
            article["_crawled_body"] = desc
        else:
            logger.warning(f"  ⚠️ 본문·description 모두 부족 — 미분석: {(article.get('link') or article.get('originallink', ''))[:60]}")
            return {
                "classification": "미분석",
                "reason": f"본문{len(body)}자 description{len(desc)}자 모두 부족",
                "confidence": "low",
            }
    return tone_analyzer.analyze_tone(article, theme_label, settings, allow_llm=allow_llm)


def run_once(dry_run: bool = False,
             max_articles: Optional[int] = None) -> dict:
    """
    파이프라인 1회 실행.
    """
    settings = settings_store.load_settings()
    themes   = settings.get("search_themes", {})

    logger.info("=" * 60)
    logger.info(f"🚀 파이프라인 시작 (dry_run={dry_run})")
    logger.info("=" * 60)

    # ── 1. 수집 ───────────────────────────────────────────
    try:
        last_collected = repository.article_last_collected_at()
    except Exception as e:
        logger.warning(f"⚠️ 마지막 수집 시각 조회 실패(1페이지만 수집): {e}")
        last_collected = None
    articles = naver_api.fetch_all_themes(settings, last_collected)
    if not articles:
        logger.warning("수집된 기사 없음 — 종료")
        return _empty_result()

    # ── 2. 관련성 필터 (규칙 기반) ─────────────────────────
    relevant = relevance.filter_relevant(articles, settings)
    if not relevant:
        logger.warning("관련성 필터 통과 0건 — 종료")
        return _empty_result(collected=len(articles))

    # ── 3. DB 중복 제거 ────────────────────────────────────
    new_articles = []
    for a in relevant:
        url = a.get("link") or a.get("originallink", "")
        if url and not repository.article_exists(url):
            new_articles.append(a)

    logger.info(
        f"📊 수집 {len(articles)} → 관련성 {len(relevant)} → 신규 {len(new_articles)}"
    )

    if not new_articles:
        logger.info("신규 기사 없음 — 종료")
        return _empty_result(collected=len(articles), relevant=len(relevant))

    if max_articles:
        new_articles = new_articles[:max_articles]
        logger.info(f"🔢 max_articles={max_articles} 적용 → {len(new_articles)}건")

    recipients = [] if dry_run else repository.recipient_list_active()

    saved_count   = 0
    sent_total    = 0
    sent_articles = 0
    monitor_cnt   = 0
    reference_cnt = 0
    llm_deadline  = time.monotonic() + TONE_TIME_BUDGET_SEC
    llm_blocked   = False     # 전역 LLM 장애 감지 시 이번 사이클 남은 기사는 LLM 생략

    # ── 4. 기사별 처리 ─────────────────────────────────────
    for idx, article in enumerate(new_articles, 1):
        try:
            title_short = (article.get("title", "")[:40]).replace("\n", " ")
            logger.info(f"\n[{idx}/{len(new_articles)}] {title_short}")

            # 테마·트랙 정보
            theme_id    = article.get("theme_id", "")
            theme_cfg   = themes.get(theme_id, {})
            track       = theme_cfg.get("track", "monitor")
            article["track"]       = track
            theme_label            = theme_cfg.get("label", theme_id)

            try:
                press = press_resolver.resolve_press_from_article(article)
            except Exception as e:
                logger.warning(f"  ⚠️ 매체명 해석 실패(빈 값): {e}")
                press = ""

            # ── 크롤링 + 트랙 분기 + 톤분류 (예외 시 미분석으로 계속) ──
            tone: Optional[dict] = None
            try:
                body = _crawl(article)

                if track != "monitor" and _body_has_priority_target(
                        body, article.get("title", ""), article.get("description", "")):
                    # STEP-3B-11: reference 본문에 SK하이닉스 등 등장 → monitor 승격
                    logger.info("  🆙 reference → monitor 승격 (본문에 SK하이닉스 등 등장)")
                    article["track"] = "monitor"
                    track = "monitor"

                if track == "monitor":
                    tone = _analyze_monitor(
                        article, body, theme_label, settings,
                        allow_llm=(not llm_blocked) and time.monotonic() < llm_deadline)
                    if (tone or {}).get("llm_status") in llm_client.GLOBAL_FAILURES and not llm_blocked:
                        llm_blocked = True
                        logger.warning(f"  🚧 LLM 전역 장애({tone['llm_status']}) — 이번 사이클 남은 기사는 LLM 생략")
            except Exception as e:
                logger.error(f"  ❌ 크롤링/톤분류 예외 — 미분석으로 저장·발송 계속: {e}", exc_info=True)
                if track == "monitor":
                    tone = {"classification": "미분석", "reason": f"처리 예외: {e}"[:200],
                            "confidence": "n/a"}

            if track == "monitor":
                monitor_cnt += 1
            else:
                reference_cnt += 1
                tone = {
                    "classification": "참고",
                    "reason":         "참고 트랙 (본문에 SK하이닉스 미등장)",
                    "confidence":     "n/a",
                    "hostile_sentences": [],
                    "total_sentences": 0,
                }

            # 요약 = description (STEP-COST-2, LLM 미사용)
            summary = summarizer.summarize(article, settings)

            # ── dry_run ──────────────────────────────────────
            if dry_run:
                cls = (tone or {}).get("classification", "—")
                logger.info(f"  🧪 [dry_run] track={track} | press={press} | "
                            f"class={cls} | summary={summary[:40]}...")
                continue

            # ── DB 저장 ──────────────────────────────────────
            article_id = repository.article_save(
                article=article,
                summary=summary,
                tone=tone,
                theme_label=theme_label,
                press=press,
                track=track,
            )
            if article_id is None:
                logger.warning("  ⚠️ DB 저장 실패 — 다음 기사")
                continue
            saved_count += 1

            # title_clean (메시지용)
            article["title_clean"] = re.sub(
                r"<[^>]+>", "", article.get("title", "")
            ).strip()

            # ── 수신자 매칭 ──────────────────────────────────
            matched = recipient_filter.match_recipients(
                article=article,
                recipients=recipients,
                track=track,
                tone=tone,
            )
            if not matched:
                repository.article_set_sent_status(article_id, repository.SENT_NO_RECIPIENTS)
                continue

            # ── 메시지 작성 + 발송 ───────────────────────────
            message = telegram_sender.build_message(
                article=article, summary=summary, tone=tone or {},
                theme_label=theme_label, press=press, track=track,
            )
            ok_count = _send_and_log(article_id, matched, message)
            sent_total += ok_count
            if ok_count:
                sent_articles += 1

        except Exception as e:
            # 한 기사의 예외가 나머지 기사 처리를 막지 않도록 격리
            logger.error(f"  ❌ 기사 처리 예외 — 다음 기사로: {e}", exc_info=True)

    # ── 4.4 재발송 (STEP-COST-2) ───────────────────────────
    resent = 0
    if not dry_run:
        try:
            resent = resend_pending()
        except Exception as e:
            logger.error(f"❌ 재발송 단계 예외(무시): {e}", exc_info=True)

    # ── 4.5 분류 분포 로깅 (STEP 3B-1) ──────────────────────
    if not dry_run and saved_count:
        from app.core.db import get_conn
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT tone_classification, COUNT(*) as n FROM articles
                WHERE id IN (SELECT id FROM articles ORDER BY id DESC LIMIT ?)
                GROUP BY tone_classification
            """, (saved_count,)).fetchall()
        dist = {r["tone_classification"] or "NULL": r["n"] for r in rows}
        logger.info(f"📊 분류 분포 (이번 실행 신규): {dict(dist)}")

    # ── 5. 결과 요약 ───────────────────────────────────────
    result = {
        "collected":     len(articles),
        "relevant":      len(relevant),
        "new":           len(new_articles),
        "monitor":       monitor_cnt,
        "reference":     reference_cnt,
        "saved":         saved_count,
        "sent_total":    sent_total,
        "sent_articles": sent_articles,
        "resent":        resent,
    }
    logger.info("=" * 60)
    logger.info(f"✅ 파이프라인 완료: {result}")
    logger.info("=" * 60)
    return result


def _send_and_log(article_id: int, recipients: list[dict], message: str) -> int:
    """수신자별 발송 + send_log 기록. 기록 실패가 다음 수신자 발송을 막지 않게 격리.
    성공 수를 반환하고 sent_status(1=1명 이상 성공, 2=전원 실패)를 갱신."""
    ok_count = 0
    for r in recipients:
        ok, err = False, ""
        try:
            ok, err = telegram_sender.send_to_chat(chat_id=r["chat_id"], message=message)
        except Exception as e:
            err = f"발송 예외: {e}"
        if ok:
            ok_count += 1
        try:
            repository.sendlog_record(article_id=article_id, recipient_id=r["id"],
                                      success=ok, error_msg=err)
        except Exception as e:
            logger.error(f"  ❌ send_log 기록 실패(발송은 계속): {e}")
    try:
        repository.article_mark_sent(article_id, success=ok_count > 0)
    except Exception as e:
        logger.error(f"  ❌ sent_status 갱신 실패: {e}")
    return ok_count


def _tone_from_row(row: dict) -> dict:
    try:
        hostile = json.loads(row.get("tone_sentences") or "[]")
    except (TypeError, ValueError):
        hostile = []
    return {
        "classification":    row.get("tone_classification") or "",
        "reason":            row.get("tone_reason") or "",
        "confidence":        row.get("tone_confidence") or "",
        "hostile_sentences": hostile if isinstance(hostile, list) else [],
        "hostile_count":     row.get("tone_hostile") or 0,
        "total_count":       row.get("tone_total") or 0,
    }


def resend_pending() -> int:
    """발송 전(저장 후 중단)·실패로 남은 최근 기사를 아직 성공 못 한 수신자에게 재발송.

    - 대상: 최근 RESEND_WINDOW_HOURS, 수집 후 RESEND_MIN_AGE_MIN 지난 기사
    - (기사, 수신자)별 실패가 RESEND_MAX_FAILS 이상이면 포기 (차단된 채팅 등)
    - 매칭 수신자가 없으면 sent_status=3으로 표시해 다시 보지 않음
    Returns: 이번에 성공한 발송 수
    """
    now = datetime.now(config.KST)
    since = (now - timedelta(hours=RESEND_WINDOW_HOURS)).isoformat()
    until = (now - timedelta(minutes=RESEND_MIN_AGE_MIN)).isoformat()
    rows = repository.articles_pending_send(since, until, RESEND_MAX_ARTICLES, RESEND_MAX_FAILS)
    if not rows:
        return 0

    recipients = repository.recipient_list_active()
    resent = 0
    for row in rows:
        try:
            track = row.get("track") or "monitor"
            tone = _tone_from_row(row)
            matched = recipient_filter.match_recipients(
                article=row, recipients=recipients, track=track, tone=tone)
            if not matched:
                if row.get("sent_status") == 0:
                    repository.article_set_sent_status(row["id"], repository.SENT_NO_RECIPIENTS)
                continue
            ok_ids, fails = repository.sendlog_status(row["id"])
            targets = [r for r in matched
                       if r["id"] not in ok_ids and fails.get(r["id"], 0) < RESEND_MAX_FAILS]
            if not targets:
                continue

            article = {
                "title_clean":      row.get("title_clean") or row.get("title") or "",
                "originallink":     row.get("original_url") or "",
                "link":             row.get("url") or "",
                "matched_keywords": row.get("matched_kw") or "",
                "pub_date_iso":     row.get("pub_date") or "",
            }
            message = "🔁 재발송 (지연 전달)\n" + telegram_sender.build_message(
                article=article, summary=row.get("summary") or "", tone=tone,
                theme_label=row.get("theme_label") or "", press=row.get("press") or "",
                track=track,
            )
            logger.info(f"🔁 재발송: id={row['id']} → {len(targets)}명")
            ok_count = _send_and_log(row["id"], targets, message)
            if ok_count == 0 and ok_ids:
                repository.article_mark_sent(row["id"], success=True)   # 이전 성공자 있음
            resent += ok_count
        except Exception as e:
            logger.error(f"  ❌ 재발송 실패 id={row.get('id')}: {e}")
    return resent


def _empty_result(collected: int = 0, relevant: int = 0) -> dict:
    return {
        "collected":     collected,
        "relevant":      relevant,
        "new":           0,
        "monitor":       0,
        "reference":     0,
        "saved":         0,
        "sent_total":    0,
        "sent_articles": 0,
        "resent":        0,
    }
