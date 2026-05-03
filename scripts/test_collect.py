# scripts/test_collect.py
"""
STEP 2A 동작 확인용.

네이버 API → 매체명 추출 → 본문 크롤링까지 단독 실행해
각 모듈이 정상 동작하는지 확인합니다.

사용법:
    python -m scripts.test_collect
"""

import logging

from app.core.logging_setup import setup_logging
from app.services import naver_api, press_resolver, crawler, settings_store

setup_logging()
log = logging.getLogger(__name__)


def main():
    settings = settings_store.load_settings()

    # ── 1. 네이버 API 호출 ─────────────────────────────────────────
    log.info("=" * 60)
    log.info("STEP 1: 네이버 API 수집")
    log.info("=" * 60)

    # 테마 하나만 골라서 빠르게 확인
    themes = settings["search_themes"]
    test_theme_id = "tier1_hynix"
    test_theme    = themes[test_theme_id]

    articles = naver_api.fetch_theme(test_theme_id, test_theme, settings)
    log.info(f"\n→ 수집 결과: {len(articles)}건\n")

    if not articles:
        log.error("❌ 기사 수집 실패. NAVER_CLIENT_ID/SECRET 확인 필요")
        return

    # ── 2. 매체명 추출 (전체 기사에 적용) ────────────────────────────
    log.info("=" * 60)
    log.info("STEP 2: 매체명 추출")
    log.info("=" * 60)
    for a in articles[:5]:
        press = press_resolver.resolve_press_from_article(a)
        title = a.get("title", "")[:40]
        log.info(f"  [{press:12s}] {title}...")

    # ── 3. 본문 크롤링 (첫 기사 1건만 테스트) ────────────────────────
    log.info("\n" + "=" * 60)
    log.info("STEP 3: 본문 크롤링 (첫 기사 1건)")
    log.info("=" * 60)
    target = articles[0]
    url = target.get("originallink") or target.get("link", "")
    log.info(f"대상 URL: {url}")

    body = crawler.fetch_body(url)
    if body:
        log.info(f"\n--- 본문 미리보기 (앞 300자) ---")
        log.info(body[:300] + "...")
    else:
        log.warning("크롤링 실패 — 사이트 차단/구조 변경 가능성")

    log.info("\n✅ STEP 2A 테스트 완료")


if __name__ == "__main__":
    main()
