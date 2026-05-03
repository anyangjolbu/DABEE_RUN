# scripts/test_ai.py
"""
STEP 2B 동작 확인용.

네이버 수집 → 관련성 필터 → (TIER 1 기사 1건 선택)
→ 본문 크롤링 → 요약 → 톤 분석까지 단독 실행.

사용법:
    python -m scripts.test_ai
"""

import logging

from app.core.logging_setup import setup_logging
from app.services import (
    naver_api,
    crawler,
    relevance,
    summarizer,
    tone_analyzer,
    settings_store,
)

setup_logging()
log = logging.getLogger(__name__)


def main():
    settings = settings_store.load_settings()
    themes   = settings["search_themes"]

    # ── 1. 수집 (TIER 1 하이닉스 테마) ────────────────────────────
    log.info("=" * 60)
    log.info("STEP 1/4: 네이버 수집")
    log.info("=" * 60)
    theme_id  = "tier1_hynix"
    theme_cfg = themes[theme_id]
    articles  = naver_api.fetch_theme(theme_id, theme_cfg, settings)
    log.info(f"→ 수집: {len(articles)}건\n")

    if not articles:
        log.error("❌ 수집 실패. 네이버 API 키 확인")
        return

    # ── 2. 관련성 필터 ────────────────────────────────────────────
    log.info("=" * 60)
    log.info("STEP 2/4: 관련성 필터")
    log.info("=" * 60)
    filtered = relevance.filter_relevant(articles, settings)
    log.info(f"→ 통과: {len(filtered)}건\n")

    if not filtered:
        log.error("❌ 모든 기사가 필터링됨")
        return

    # ── 3. 첫 기사로 본문 크롤링 + 요약 + 톤 분석 ─────────────────
    target = filtered[0]
    title  = target.get("title", "")[:60]
    url    = target.get("originallink") or target.get("link", "")
    log.info(f"테스트 대상: {title}")
    log.info(f"URL: {url}\n")

    log.info("=" * 60)
    log.info("STEP 3/4: 본문 크롤링 + 요약")
    log.info("=" * 60)
    body = crawler.fetch_body(url)
    if body:
        target["_crawled_body"] = body
        log.info(f"본문: {len(body)}자\n")
    else:
        log.info("본문 크롤링 실패 — description으로 요약 진행\n")

    target["tier"] = theme_cfg["tier"]
    summary = summarizer.summarize(target, settings)
    log.info("--- 요약 ---")
    log.info(summary)
    log.info("")

    # ── 4. 톤 분석 ────────────────────────────────────────────────
    log.info("=" * 60)
    log.info("STEP 4/4: 비우호 톤 분석")
    log.info("=" * 60)
    company = theme_cfg["label"]
    result = tone_analyzer.analyze_tone(target, company, settings)
    log.info(f"레벨: {result['level']}")
    log.info(f"톤:   {result['tone']}")
    log.info(f"비우호 {result['hostile_count']}/{result['total_count']}문장")
    if result["hostile_sentences"]:
        log.info("--- 비우호 문장 ---")
        for i, s in enumerate(result["hostile_sentences"], 1):
            log.info(f"  {i}. {s[:100]}...")

    log.info("\n✅ STEP 2B 테스트 완료")


if __name__ == "__main__":
    main()
