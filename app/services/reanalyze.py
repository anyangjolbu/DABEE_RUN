"""
미분석/LLM에러 monitor 레코드 일괄 재분석.

스크립트와 어드민 엔드포인트, 스케줄러가 모두 호출하는 단일 진입점.
"""
import logging
from typing import Optional

from app.core.db import get_conn
from app.services.crawler import fetch_body_full
from app.services.settings_store import load_settings
from app.services.tone_analyzer import analyze_tone

logger = logging.getLogger(__name__)


def reanalyze_unanalyzed(limit: int = 50) -> dict:
    """
    track='monitor' AND tone_classification IN ('미분석','LLM에러') 인
    레코드를 다시 톤 분석. 신규 결과로 DB 갱신.

    Returns:
        {"target": N, "비우호": N, "양호": N, "미분석": N, "에러": N, "items": [...]}
    """
    settings = load_settings()
    stats = {"비우호": 0, "양호": 0, "미분석": 0, "에러": 0}
    items: list[dict] = []

    with get_conn() as conn:
        rows = conn.execute("""
            SELECT id, url, original_url, title, title_clean, description,
                   theme_id, theme_label, matched_kw
            FROM articles
            WHERE track='monitor'
              AND tone_classification IN ('미분석', 'LLM에러')
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()

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
                           tone_total          = ?
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
