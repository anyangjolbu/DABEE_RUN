"""
파이프라인 오케스트레이터.

STEP 4A-1:
- 테마별 track ('monitor' | 'reference')에 따라 분기
- monitor: 본문크롤링 → 톤분류 → DB저장 → 텔레그램(권한 매칭)
- reference: 본문크롤링 X, 톤분류 X, DB저장만 + 텔레그램은 reference 권한자만
"""

import logging
import re
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
    """
    settings = settings_store.load_settings()
    themes   = settings.get("search_themes", {})

    logger.info("=" * 60)
    logger.info(f"🚀 파이프라인 시작 (dry_run={dry_run})")
    logger.info("=" * 60)

    # ── 1. 수집 ───────────────────────────────────────────
    articles = naver_api.fetch_all_themes(settings)
    if not articles:
        logger.warning("수집된 기사 없음 — 종료")
        return _empty_result()

    # ── 2. 관련성 필터 ─────────────────────────────────────
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

    # ── 4. 기사별 처리 ─────────────────────────────────────
    for idx, article in enumerate(new_articles, 1):
        title_short = (article.get("title", "")[:40]).replace("\n", " ")
        logger.info(f"\n[{idx}/{len(new_articles)}] {title_short}")

        # 테마·트랙 정보
        theme_id    = article.get("theme_id", "")
        theme_cfg   = themes.get(theme_id, {})
        track       = theme_cfg.get("track", "monitor")
        article["track"]       = track
        article["tier"]        = theme_cfg.get("tier", 1)
        theme_label            = theme_cfg.get("label", theme_id)

        press = press_resolver.resolve_press_from_article(article)

        # ── 트랙별 분기 ──────────────────────────────────
        tone = None

        if track == "monitor":
            monitor_cnt += 1

            # 본문 + 이미지 크롤링 (1회 HTTP 요청)
            url = article.get("originallink") or article.get("link", "")
            body, image_url = crawler.fetch_body_full(url)
            if body:
                article["_crawled_body"] = body
            if image_url:
                article["image_url"] = image_url

            # 톤 분류
            tone = tone_analyzer.analyze_tone(article, theme_label, settings)

            # 요약
            summary = summarizer.summarize(article, settings)

        else:  # reference
            reference_cnt += 1
            # 본문 크롤링 X, 톤 분류 X
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
            continue

        # ── 메시지 작성 + 발송 ───────────────────────────
        message = telegram_sender.build_message(
            article=article, summary=summary, tone=tone or {},
            theme_label=theme_label, press=press, track=track,
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

    # ── 4.5 분류 분포 로깅 (STEP 3B-1) ──────────────────────
    if not dry_run:
        from collections import Counter
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
    }
    logger.info("=" * 60)
    logger.info(f"✅ 파이프라인 완료: {result}")
    logger.info("=" * 60)
    return result


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
    }