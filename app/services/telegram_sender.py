# app/services/telegram_sender.py
"""
텔레그램 메시지 전송.

PR팀이 모바일에서 한눈에 볼 수 있도록 다음 정보를 압축해 표시:
    - 매체명 + 제목
    - 원문 링크
    - 테마 + 티어
    - 매칭 키워드 (해시태그)
    - 발행일시 (KST)
    - 비우호 톤 (TIER 1만, 경고/주의 시 인용 문장 포함)
    - GPT 요약

HTML/Markdown 모드 대신 plain text를 씁니다. 텔레그램의 자동 링크
미리보기로도 충분히 가독성이 좋고, 이스케이프 버그 위험이 없어요.
"""

import logging
import time
from datetime import datetime
from email.utils import parsedate_to_datetime

import requests

from app import config

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


# ── 헬퍼 ─────────────────────────────────────────────────────────────
def _tier_label(tier: int) -> str:
    return {1: "🔴 TIER 1", 2: "🟠 TIER 2", 3: "🟡 TIER 3"}.get(
        tier, f"TIER {tier}"
    )


def _format_pub_date(article: dict) -> str:
    """
    article의 pubDate(RFC2822 또는 ISO)를 'YYYY-MM-DD HH:MM (KST)'로.
    """
    raw = article.get("pubDate", "") or article.get("pub_date_iso", "")
    if not raw:
        return "알 수 없음"
    try:
        if "T" in raw or len(raw) >= 19 and "-" in raw:
            # 이미 ISO
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            # RFC2822 (네이버 API 원본)
            dt = parsedate_to_datetime(raw)
        return dt.astimezone(config.KST).strftime("%Y-%m-%d %H:%M") + " (KST)"
    except Exception:
        return raw


def _format_keywords(matched_keywords) -> str:
    """매칭 키워드를 #해시태그 문자열로."""
    if isinstance(matched_keywords, list):
        items = matched_keywords
    elif isinstance(matched_keywords, str):
        items = [k.strip() for k in matched_keywords.split(",")]
    else:
        return ""
    return " ".join(f"#{k}" for k in items if k)


def build_message(article: dict, summary: str, tone: dict,
                  theme_label: str, press: str) -> str:
    """
    텔레그램에 보낼 메시지 본문 작성.
    """
    tier   = int(article.get("tier", 3))
    title  = article.get("title_clean") or article.get("title", "제목 없음")
    link   = article.get("originallink") or article.get("link", "")

    # 매체명 prefix
    title_line = f"<{press}> {title}" if press else title

    # 테마 + 티어 한 줄
    tier_str  = _tier_label(tier)
    parts = []
    if theme_label:
        parts.append(f"테마: {theme_label}")
    if tier_str:
        parts.append(tier_str)
    theme_tier_line = " | ".join(parts)

    # 키워드, 발행일
    kw_line   = _format_keywords(article.get("matched_keywords", []))
    pub_line  = f"발행: {_format_pub_date(article)}"

    SEP = "─" * 18

    lines = [
        title_line,
        link,
        SEP,
        theme_tier_line,
    ]
    if kw_line:
        lines.append(f"키워드: {kw_line}")
    lines.append(pub_line)

    # ── 비우호 톤 (TIER 1만) ─────────────────────────────────
    if tier == 1 and tone and tone.get("level"):
        level = tone["level"]
        h     = tone.get("hostile_count", 0)
        total = tone.get("total_count", 0)
        lines.append(f"보도톤: [{level}] 비우호 {h}/{total}문장")

        # 경고는 최대 3문장, 주의는 1문장 인용
        if level in ("경고", "주의"):
            limit = 3 if level == "경고" else 1
            for s in tone.get("hostile_sentences", [])[:limit]:
                short = s[:60] + ("..." if len(s) > 60 else "")
                lines.append(f"  ㄴ {short}")

    lines.append(SEP)
    lines.append("요약")
    lines.append(summary or "(요약 없음)")
    lines.append(SEP)

    return "\n".join(lines)


# ── 발송 ─────────────────────────────────────────────────────────────
def send_to_chat(chat_id: str, message: str,
                 disable_preview: bool = False,
                 retry: int = 3, delay: int = 2) -> tuple[bool, str]:
    """
    단일 chat_id에게 메시지 전송. (success, error_msg) 반환.
    """
    if not config.TELEGRAM_BOT_TOKEN:
        return False, "TELEGRAM_BOT_TOKEN 미설정"

    url = TELEGRAM_API.format(token=config.TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id":                  chat_id,
        "text":                     message,
        "disable_web_page_preview": disable_preview,
    }

    last_err = ""
    for attempt in range(retry):
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info(f"  ✅ 텔레그램 전송 성공 → {chat_id}")
                return True, ""
            last_err = f"HTTP {resp.status_code}: {resp.text[:120]}"
            logger.warning(f"  텔레그램 실패 [{attempt+1}/{retry}] {last_err}")
        except Exception as e:
            last_err = str(e)
            logger.warning(f"  텔레그램 예외 [{attempt+1}/{retry}]: {e}")
        time.sleep(delay)

    return False, last_err
