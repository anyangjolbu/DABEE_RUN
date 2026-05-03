# app/services/telegram_sender.py
"""
텔레그램 메시지 전송 (STEP 4A-2).

PR팀이 모바일에서 한눈에 볼 수 있도록 다음 정보를 압축해 표시:
    - [트랙 배지] 매체명 + 제목
    - 원문 링크
    - 테마, 매칭 키워드, 발행일시(KST)
    - monitor 트랙: 톤 분류 (비우호/일반/미분석) + 비우호문장 인용
    - reference 트랙: '참고' 배지만, 톤 분석 없음
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
def _track_badge(track: str, classification: str = "") -> str:
    """트랙 + 분류 → 배지 문자열."""
    if track == "reference":
        return "⚪ 참고"
    if classification == "비우호":
        return "🔴 비우호"
    if classification == "일반":
        return "🟢 일반"
    if classification == "미분석":
        return "⚫ 미분석"
    return "🔴 모니터"


def _format_pub_date(article: dict) -> str:
    raw = article.get("pubDate", "") or article.get("pub_date_iso", "")
    if not raw:
        return "알 수 없음"
    try:
        if "T" in raw or (len(raw) >= 19 and "-" in raw):
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            dt = parsedate_to_datetime(raw)
        return dt.astimezone(config.KST).strftime("%Y-%m-%d %H:%M") + " (KST)"
    except Exception:
        return raw


def _format_keywords(matched_keywords) -> str:
    if isinstance(matched_keywords, list):
        items = matched_keywords
    elif isinstance(matched_keywords, str):
        items = [k.strip() for k in matched_keywords.split(",")]
    else:
        return ""
    return " ".join(f"#{k}" for k in items if k)


def build_message(article: dict, summary: str, tone: dict,
                  theme_label: str, press: str,
                  track: str = "monitor") -> str:
    """
    텔레그램 메시지 본문 작성 (track 인자 추가).

    Args:
        article: 기사 dict
        summary: GPT 요약
        tone:    톤 분류 결과 (monitor만, reference는 빈 dict)
        theme_label: 테마 라벨 (예: '🔴 SK하이닉스')
        press: 매체명
        track: 'monitor' | 'reference'
    """
    title  = article.get("title_clean") or article.get("title", "제목 없음")
    link   = article.get("originallink") or article.get("link", "")

    # 분류 추출 (monitor만)
    classification = (tone or {}).get("classification", "")
    badge = _track_badge(track, classification)

    # 첫 줄: [배지] <매체> 제목
    title_line = f"[{badge}] <{press}> {title}" if press else f"[{badge}] {title}"

    # 테마 라인
    theme_line = f"테마: {theme_label}" if theme_label else ""

    # 키워드, 발행일
    kw_line  = _format_keywords(article.get("matched_keywords", []))
    pub_line = f"발행: {_format_pub_date(article)}"

    SEP = "─" * 18

    lines = [title_line, link, SEP]
    if theme_line:
        lines.append(theme_line)
    if kw_line:
        lines.append(f"키워드: {kw_line}")
    lines.append(pub_line)

    # ── 톤 분류 (monitor만) ─────────────────────────────────
    if track == "monitor" and tone and classification:
        h     = tone.get("hostile_count", 0)
        total = tone.get("total_count", 0)
        conf  = tone.get("confidence", "")
        reason = tone.get("reason", "") or ""

        cls_line = f"분류: [{classification}]"
        if conf:
            cls_line += f" (신뢰도 {conf})"
        if total:
            cls_line += f" — 비우호 {h}/{total}문장"
        lines.append(cls_line)

        # 비우호 분류면 근거 + 인용문장
        if classification == "비우호":
            if reason:
                short_reason = reason[:80] + ("..." if len(reason) > 80 else "")
                lines.append(f"근거: {short_reason}")
            for s in tone.get("hostile_sentences", [])[:3]:
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
    """단일 chat_id에게 메시지 전송. (success, error_msg) 반환."""
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