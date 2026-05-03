# app/services/report_builder.py
"""
일간 리포트 생성 + 텔레그램 발송.

매일 지정 시각(settings.daily_report_hour_kst, 기본 7시)에 스케줄러가
run_daily_report()를 호출합니다. 전날 수집된 기사 상위 N건을 요약해
receive_daily_report 권한이 있는 수신자에게 발송하고 DB에 기록합니다.
"""

import logging
from datetime import datetime, timedelta

from app import config
from app.core import repository as repo
from app.services import settings_store, telegram_sender

logger = logging.getLogger(__name__)


def build_report_body(articles: list[dict], date_str: str) -> str:
    """텔레그램 일간 리포트 본문 구성."""
    SEP = "─" * 22
    lines = [
        f"📰 {date_str} 일간 모니터링 리포트",
        f"총 {len(articles)}건 주요 보도",
        SEP,
    ]

    tier_emoji = {1: "🔴", 2: "🟠", 3: "🟡"}
    tone_mark  = {"경고": "⚠️ ", "주의": "🔔 "}

    for i, a in enumerate(articles, 1):
        tier      = a.get("tier", 3)
        tone      = a.get("tone_level") or ""
        title     = a.get("title_clean") or a.get("title", "(제목 없음)")
        url       = a.get("original_url") or a.get("url", "")
        press     = a.get("press", "")
        summary   = a.get("summary", "")
        theme_lbl = a.get("theme_label", "")

        prefix = f"{tier_emoji.get(tier, '⚪')} {tone_mark.get(tone, '')}"
        source = f"[{press or theme_lbl}] " if (press or theme_lbl) else ""

        lines.append(f"{i}. {prefix}{source}{title}")
        if url:
            lines.append(url)
        if summary:
            lines.append(f"   {summary}")
        lines.append("")

    lines.append(SEP)
    lines.append("DABEE Run — SK하이닉스 PR팀")
    return "\n".join(lines)


def run_daily_report(date_str: str = None) -> dict:
    """
    일간 리포트 실행.

    Args:
        date_str: 대상 날짜 YYYY-MM-DD (KST). None이면 전날.

    Returns:
        {"date": str, "sent": int, "total": int, "articles": int}
        또는 {"skipped": True, ...}
    """
    settings = settings_store.load_settings()
    if not settings.get("daily_report_enabled", True):
        logger.info("일간 리포트 비활성화됨")
        return {"skipped": True}

    if date_str is None:
        yesterday = datetime.now(config.KST) - timedelta(days=1)
        date_str  = yesterday.strftime("%Y-%m-%d")

    # 중복 발송 방지
    if repo.report_get(date_str):
        logger.info(f"일간 리포트 이미 발송됨: {date_str}")
        return {"skipped": True, "date": date_str}

    top_n    = int(settings.get("daily_report_top_n", 5))
    articles = repo.article_daily(date_str, limit=top_n)

    if not articles:
        logger.info(f"일간 리포트: {date_str} 수집 기사 없음")
        repo.report_save(date_str, "(해당 날짜 수집 기사 없음)", 0)
        return {"date": date_str, "sent": 0, "total": 0, "articles": 0}

    body       = build_report_body(articles, date_str)
    recipients = repo.recipient_list_active()
    targets    = [r for r in recipients if r.get("receive_daily_report")]

    success = 0
    for r in targets:
        ok, err = telegram_sender.send_to_chat(
            chat_id=r["chat_id"],
            message=body,
            disable_preview=True,
        )
        if ok:
            success += 1
        else:
            logger.warning(f"일간 리포트 발송 실패 → {r['chat_id']}: {err}")

    repo.report_save(date_str, body, success)
    logger.info(f"📋 일간 리포트 완료: {date_str} → {success}/{len(targets)}명 / {len(articles)}건")
    return {
        "date": date_str, "sent": success,
        "total": len(targets), "articles": len(articles),
    }
