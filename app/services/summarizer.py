# app/services/summarizer.py
"""
기사 요약 (Gemini Flash 계열).

본문 크롤링은 호출자(pipeline)가 담당하고, 이 모듈은
"이미 받은 텍스트를 요약"만 합니다.

STEP-3B-34: tier 분기·gpt_model_tier* 키 등 구버전 잔존 일소.
STEP-3B-40: 요약은 thinking_budget=0 으로 비활성 (lite/flash 공통).
STEP-3B-41: 503/UNAVAILABLE/429 등 일시 오류에 대한 재시도 로직 추가.
"""

import logging
import re
import time

from google.genai import types

from app.services.gemini_client import get_client

logger = logging.getLogger(__name__)

DEFAULT_MODEL    = "gemini-flash-lite-latest"
MAX_OUTPUT_TOKEN = 1024
BODY_LIMIT       = 4000
RETRY_MAX        = 3      # STEP-3B-41
RETRY_DELAY      = 2


def _strip_markdown(text: str) -> str:
    """STEP-3B-37: 모델이 가끔 마크다운/글머리표로 응답하는 경우 평문화."""
    if not text:
        return text
    t = re.sub(r"\*\*+", "", text)
    t = re.sub(r"`+", "", t)
    t = re.sub(r"(?m)^\s*#{1,6}\s*", "", t)
    t = re.sub(r"(?m)^\s*(?:[\*\-\u2022\u30FB\u25AA\u25A0]|\d+\.)\s+", "", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _clean(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _is_transient(err: Exception) -> bool:
    """503/UNAVAILABLE/429/timeout 등 재시도 가치가 있는 오류인지 판별."""
    s = str(err)
    return any(k in s for k in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED",
                                 "DEADLINE_EXCEEDED", "Timeout", "timeout"))


def summarize(article: dict, settings: dict) -> str:
    """기사 1건 요약. 실패 시 description 또는 안내 문구 반환."""
    title       = _clean(article.get("title", ""))
    description = _clean(article.get("description", ""))
    body        = article.get("_crawled_body", "")

    model = settings.get("gpt_model_summary") or DEFAULT_MODEL
    system_prompt = (
        settings.get("summary_system_prompt")
        or settings.get("gpt_system_prompt")
        or ""
    )

    if body:
        user_content = f"제목: {title}\n\n본문:\n{body[:BODY_LIMIT]}"
        logger.info(f"  📝 요약(본문 {min(len(body), BODY_LIMIT)}자) model={model}")
    else:
        user_content = f"제목: {title}\n\n부가 정보: {description}"
        logger.info(f"  📝 요약(description) model={model}")

    full_prompt = f"{system_prompt}\n\n{user_content}".strip()

    client = get_client()
    if client is None:
        logger.warning("Gemini 미사용 — description 반환")
        return description or "요약 불가 (API 키 미설정)"

    last_err = None
    for attempt in range(1, RETRY_MAX + 1):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=MAX_OUTPUT_TOKEN,
                    temperature=0.3,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            summary = _strip_markdown((resp.text or "").strip())

            # 잘림 진단
            try:
                fin = resp.candidates[0].finish_reason if resp.candidates else None
                if fin and str(fin).upper().endswith("MAX_TOKENS"):
                    logger.warning(
                        f"  ⚠️ 요약 잘림(MAX_TOKENS) — model={model} len={len(summary)}자"
                    )
            except Exception:
                pass

            if not summary:
                return description or "요약 실패 (빈 응답)"
            return summary

        except Exception as e:
            last_err = e
            if _is_transient(e) and attempt < RETRY_MAX:
                logger.warning(
                    f"  ⏳ [{attempt}/{RETRY_MAX}] 일시 오류, {RETRY_DELAY}s 후 재시도: {str(e)[:120]}"
                )
                time.sleep(RETRY_DELAY)
                continue
            logger.error(f"❌ 요약 실패 (attempt={attempt}): {e}")
            return description or "요약 실패 (예외)"

    logger.error(f"❌ 요약 실패 (모든 재시도 소진): {last_err}")
    return description or "요약 실패 (재시도 소진)"
