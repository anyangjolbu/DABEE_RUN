# app/services/summarizer.py
"""
기사 요약 (Gemini).

본문 크롤링은 호출자(pipeline)가 담당하고, 이 모듈은
"이미 받은 텍스트를 요약"만 합니다. 책임을 분리해 테스트가 쉽고,
요약만 따로 재실행하기도 쉬워집니다.

티어별로 다른 모델을 쓸 수 있게 settings에서 모델명을 읽습니다.
- TIER 1 (하이닉스·삼성): 가장 정확한 모델 권장
- TIER 2/3 (산업·경쟁사): 가벼운 모델로 비용 절감
"""

import logging
import re

from google.genai import types

from app.services.gemini_client import get_client

logger = logging.getLogger(__name__)


def _clean(text: str) -> str:
    """HTML 태그 제거."""
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _resolve_model(tier: int, settings: dict) -> str:
    """티어에 맞는 모델명 반환. 미설정 시 안전한 기본값."""
    key = {1: "gpt_model_tier1",
           2: "gpt_model_tier2",
           3: "gpt_model_tier3"}.get(tier, "gpt_model_tier3")
    return settings.get(key, "gemini-flash-lite-latest")


def summarize(article: dict, settings: dict) -> str:
    """
    기사 1건을 요약해 반환.

    Args:
        article: 기사 dict. 다음 키를 사용:
            - title: 제목
            - description: 네이버 API description (폴백용)
            - _crawled_body: 크롤링된 본문 (있으면 우선 사용)
            - tier: 티어 (모델 선택용)
        settings: settings.json (gpt_system_prompt, gpt_model_tier* 사용)

    Returns:
        요약 문자열. 실패 시 description 또는 "요약 실패" 반환.
    """
    title       = _clean(article.get("title", ""))
    description = _clean(article.get("description", ""))
    body        = article.get("_crawled_body", "")
    tier        = int(article.get("tier", 3))

    model         = _resolve_model(tier, settings)
    system_prompt = settings.get("gpt_system_prompt", "")

    # 본문이 있으면 본문 기반, 없으면 description 기반
    if body:
        user_content = f"제목: {title}\n\n본문:\n{body[:2000]}"
        logger.info(f"  📝 요약(본문): tier={tier} model={model}")
    else:
        user_content = f"제목: {title}\n\n부가 정보: {description}"
        logger.info(f"  📝 요약(description): tier={tier} model={model}")

    full_prompt = f"{system_prompt}\n\n{user_content}"

    client = get_client()
    if client is None:
        logger.warning("Gemini 미사용 — description 반환")
        return description or "요약 불가 (API 키 미설정)"

    try:
        resp = client.models.generate_content(
            model=model,
            contents=full_prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=400,
                temperature=0.3,   # 약간의 자연스러움 + 안정적
            ),
        )
        summary = (resp.text or "").strip()
        if not summary:
            return description or "요약 실패 (빈 응답)"
        return summary

    except Exception as e:
        logger.error(f"❌ 요약 실패: {e}")
        return description or "요약 실패 (예외)"
