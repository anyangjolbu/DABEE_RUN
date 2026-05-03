# app/services/pipeline.py
"""
파이프라인 오케스트레이터.

전체 흐름을 한 함수(run_once)에 담아 스케줄러·관리자 페이지·테스트
스크립트가 모두 같은 진입점을 사용하도록 합니다.

흐름:
    1. settings 로드
    2. 네이버 수집 (테마별)
    3. 관련성 필터
    4. DB 중복 제거
    5. 각 신규 기사:
        - TIER 1이면 본문 크롤링 + 톤 분석
        - 요약
        - 매체명 추출
        - DB 저장
        - 수신자 매칭 → 텔레그램 발송
        - send_log 기록
    6. 결과 요약 dict 반환

dry_run=True 면 텔레그램 발송과 DB 저장을 건너뜁니다 (테스트용).
"""

import logging
from typing import Optional

from app.core import repository
from app.services import (
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


def run_once(dry_run: bool = False,
             max_articles: Optional[int] = None) -> dict:
    """
    파이프라인 1회 실행.

    Args:
        dry_run: True면 DB 저장·텔레그램 발송 스킵 (개발용 검증)
        max_articles: 처리할 신규 기사 최대 개수 (None이면 전체)

    Returns:
        {
            "collected":    int,   # 네이버에서 받은 기사 수
            "relevant":     int,   # 관련성 통과 수
            "new":          int,   # DB 중복 제거 후 신규 수
            "saved":        int,   # 실제 DB 저장 성공 수
            "sent_total":   int,   # 텔레그램 발송 성공 (수신자 단위 합산)
            "sent_articles":int,   # 1명 이상에게 발송된 기사 수
        }
    """
    settings = settings_store.load_settings()
    themes   = settings.get("search_themes", {})

    logger.info("=" * 60)
    logger.info(f"🚀 파이프라인 시작 (dry_run={dry_run})")
    logger.info("=" * 60)

    # ── 1. 수집 ────────────────────────────────────────────
    articles = naver_api.fetch_all_themes(settings)
    if not articles:
        logger.warning("수집된 기사 없음 — 파이프라인 종료")
        return {"collected": 0, "relevant": 0, "new": 0,
                "saved": 0, "sent_total": 0, "sent_articles": 0}

    # ── 2. 관련성 필터 ──────────────────────────────────────
    relevant = relevance.filter_relevant(articles, settings)
    if not relevant:
        logger.warning("관련성 필터 통과 0건 — 종료")
        return {"collected": len(articles), "relevant": 0, "new": 0,
                "saved": 0, "sent_total": 0, "sent_articles": 0}

    # ── 3. DB 중복 제거 ─────────────────────────────────────
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
        return {"collected": len(articles), "relevant": len(relevant),
                "new": 0, "saved": 0, "sent_total": 0, "sent_articles": 0}

    if max_articles:
        new_articles = new_articles[:max_articles]
        logger.info(f"🔢 max_articles={max_articles} 적용 → {len(new_articles)}건")

    # 활성 수신자 한 번만 로드
    recipients = [] if dry_run else repository.recipient_list_active()

    saved_count   = 0
    sent_total    = 0
    sent_articles = 0

    # ── 4. 기사별 처리 ──────────────────────────────────────
    for idx, article in enumerate(new_articles, 1):
        title_short = (article.get("title", "")[:40]).replace("\n", " ")
        logger.info(f"\n[{idx}/{len(new_articles)}] {title_short}")

        # 테마 정보 주입
        theme_id  = article.get("theme_id", "")
        theme_cfg = themes.get(theme_id, {})
        article["tier"]        = theme_cfg.get("tier", 3)
        theme_label            = theme_cfg.get("label", theme_id)

        # 매체명
        press = press_resolver.resolve_press_from_article(article)

        tier         = article["tier"]
        tone_enabled = tier == 1 and theme_cfg.get("tone_analysis", False)

        # ── TIER 1: 본문 크롤링 ──────────────────────────────
        if tone_enabled:
            url = article.get("originallink") or article.get("link", "")
            body = crawler.fetch_body(url)
            if body:
                article["_crawled_body"] = body

        # ── 요약 ──────────────────────────────────────────────
        summary = summarizer.summarize(article, settings)

        # ── 톤 분석 ───────────────────────────────────────────
        tone = None
        if tone_enabled:
            tone = tone_analyzer.analyze_tone(article, theme_label, settings)
            article["tone_level"] = tone.get("level")

        if dry_run:
            logger.info(f"  🧪 [dry_run] press={press} | summary={summary[:40]}...")
            if tone:
                logger.info(f"  🧪 [dry_run] tone={tone['level']} ({tone['hostile_count']}/{tone['total_count']})")
            continue

        # ── DB 저장 ───────────────────────────────────────────
        article_id = repository.article_save(
            article=article,
            summary=summary,
            tone=tone,
            theme_label=theme_label,
            press=press,
        )
        if article_id is None:
            logger.warning("  ⚠️ DB 저장 실패 — 다음 기사")
            continue
        saved_count += 1

        # ── 수신자 매칭 ───────────────────────────────────────
        # title_clean을 메시지에 쓰기 위해 미리 채워둠
        import re
        article["title_clean"] = re.sub(r"<[^>]+>", "", article.get("title", "")).strip()

        matched = recipient_filter.match_recipients(article, recipients)
        if not matched:
            continue

        # ── 메시지 작성 + 발송 ────────────────────────────────
        message = telegram_sender.build_message(
            article=article, summary=summary, tone=tone or {},
            theme_label=theme_label, press=press,
        )

        article_sent = False
        for r in matched:
            ok, err = telegram_sender.send_to_chat(
                chat_id=r["chat_id"], message=message,
            )
            repository.sendlog_record(
                article_id=article_id, recipient_id=r["id"],
                success=ok, error_msg=err,
            )
            if ok:
                sent_total  += 1
                article_sent = True

        if article_sent:
            sent_articles += 1
            repository.article_mark_sent(article_id, success=True)
        else:
            repository.article_mark_sent(article_id, success=False)

    # ── 5. 결과 요약 ────────────────────────────────────────
    result = {
        "collected":     len(articles),
        "relevant":      len(relevant),
        "new":           len(new_articles),
        "saved":         saved_count,
        "sent_total":    sent_total,
        "sent_articles": sent_articles,
    }
    logger.info("=" * 60)
    logger.info(f"✅ 파이프라인 완료: {result}")
    logger.info("=" * 60)
    return result
