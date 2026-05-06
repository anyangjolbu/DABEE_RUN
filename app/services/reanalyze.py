"""
미분석/LLM에러 monitor 레코드 일괄 재분석.

스크립트와 어드민 엔드포인트, 스케줄러가 모두 호출하는 단일 진입점.

STEP-3B-38: 무한 재시도 방지 cap.
- 'Gemini 관련없음' 정상 판정도 '미분석'으로 저장돼 동일 분석 결과를
  계속 생산하며 토큰을 낭비하던 문제. articles.reanalyze_attempts를
  매 호출마다 +1, MAX_REANALYZE_ATTEMPTS 도달 시 대상에서 제외.
- '진짜 LLM 에러'는 보통 1~2회 안에 회복되므로 cap을 넉넉히 잡아도
  과한 토큰 소모 없음.
"""
import logging
from typing import Optional

from app.core.db import get_conn
from app.services.crawler import fetch_body_full
from app.services.settings_store import load_settings
from app.services.tone_analyzer import analyze_tone

logger = logging.getLogger(__name__)

# 동일 기사를 재분석하는 최대 횟수 (초기 파이프라인 분석은 카운트 X)
MAX_REANALYZE_ATTEMPTS = 3


def reanalyze_unanalyzed(limit: int = 50) -> dict:
    """
    track='monitor' AND tone_classification IN ('미분석','LLM에러')
    AND reanalyze_attempts < MAX_REANALYZE_ATTEMPTS 인 레코드를 다시 톤 분석.

    Returns:
        {"target": N, "비우호": N, "양호": N, "미분석": N, "에러": N, "items": [...]}
    """
    settings = load_settings()
    stats = {"비우호": 0, "양호": 0, "미분석": 0, "에러": 0}
    items: list[dict] = []

    with get_conn() as conn:
        rows = conn.execute("""
            SELECT id, url, original_url, title, title_clean, description,
                   theme_id, theme_label, matched_kw, reanalyze_attempts
            FROM articles
            WHERE track='monitor'
              AND tone_classification IN ('미분석', 'LLM에러')
              AND COALESCE(reanalyze_attempts, 0) < ?
            ORDER BY id DESC
            LIMIT ?
        """, (MAX_REANALYZE_ATTEMPTS, limit)).fetchall()

    target_n = len(rows)
    if target_n == 0:
        logger.info("🔄 재분석 대상 없음")
        return {"target": 0, **stats, "items": []}

    logger.info(f"🔄 재분석 시작: {target_n}건 (limit={limit})")

    for r in rows:
        d = dict(r)
        url = d["original_url"] or d["url"]
        try:
            body, _image = fetch_body_full(url)
            article = {
                "title":         d["title"],
                "description":   d["description"],
                "_crawled_body": body or "",
            }
            result = analyze_tone(article, d["theme_label"] or "", settings)
            cls = result.get("classification", "미분석")
            stats[cls] = stats.get(cls, 0) + 1

            with get_conn() as conn:
                conn.execute("""
                    UPDATE articles
                       SET tone_classification = ?,
                           tone_reason         = ?,
                           tone_confidence     = ?,
                           tone_level          = ?,
                           tone_hostile        = ?,
                           tone_total          = ?,
                           reanalyze_attempts  = COALESCE(reanalyze_attempts, 0) + 1
                     WHERE id = ?
                """, (
                    cls,
                    result.get("reason"),
                    result.get("confidence"),
                    result.get("level"),
                    int(result.get("hostile_count", 0) or 0),
                    int(result.get("total_count", 0) or 0),
                    d["id"],
                ))
                conn.commit()

            items.append({
                "id":             d["id"],
                "title":          d["title_clean"],
                "classification": cls,
                "confidence":     result.get("confidence"),
            })
        except Exception as e:
            stats["에러"] += 1
            logger.error(f"  ❌ id={d['id']} 재분석 실패: {e}")
            # 크롤러/네트워크 예외도 cap 정책 적용 — 같은 기사 무한 재시도 방지
            try:
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE articles "
                        "SET reanalyze_attempts = COALESCE(reanalyze_attempts, 0) + 1 "
                        "WHERE id = ?",
                        (d["id"],),
                    )
                    conn.commit()
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
    )
    return {"target": target_n, **stats, "items": items}
