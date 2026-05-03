# app/services/gemini_client.py
"""
Gemini API 클라이언트 싱글톤.

3개 모듈(relevance, summarizer, tone_analyzer)이 공통으로 사용하므로
클라이언트 생성을 한 곳에서 관리합니다. 키가 없으면 None을 반환해
호출자가 적절히 폴백하도록 합니다.
"""

import logging
from typing import Optional

from google import genai

from app import config

logger = logging.getLogger(__name__)

_client: Optional[genai.Client] = None


def get_client() -> Optional[genai.Client]:
    """
    Gemini 클라이언트를 반환. 키가 없으면 None.

    None을 반환받은 호출자는 자체적으로 폴백 처리해야 합니다.
    (예: 요약 → description으로 대체, 톤 → "양호" 처리)
    """
    global _client

    if _client is not None:
        return _client

    if not config.GEMINI_API_KEY:
        logger.warning("⚠️ GEMINI_API_KEY 미설정 — AI 기능 비활성화")
        return None

    try:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
        logger.info("✅ Gemini 클라이언트 초기화 완료")
        return _client
    except Exception as e:
        logger.error(f"❌ Gemini 클라이언트 초기화 실패: {e}")
        return None


def reset_client() -> None:
    """테스트용 / API 키 변경 시 클라이언트 재생성."""
    global _client
    _client = None
