# app/services/settings_store.py
"""
사용자 설정(settings.json) 로드·저장.

환경변수와 달리 운영 중에 자주 바뀌는 값들을 다룹니다:
- 검색 주기, 만료 시간
- 검색 테마(키워드 묶음)
- GPT 프롬프트, 모델 선택
- 도메인/제목 블랙리스트
- 일간 리포트 시각

DEFAULT_SETTINGS와 저장된 값을 merge해서 반환하므로, 새 설정 항목이
추가되어도 기존 settings.json을 마이그레이션할 필요가 없습니다.
"""

import json
import logging

from app import config

logger = logging.getLogger(__name__)


# ── 기본값 ────────────────────────────────────────────────────────────
DEFAULT_SETTINGS: dict = {
    # 스케줄
    "schedule_interval_minutes": 10,
    "article_expire_hours":      1,

    # 네이버 API
    "naver_display_count": 20,
    "api_retry_count":     3,
    "api_retry_delay":     2,

    # GPT 모델
    "gpt_model_tier1": "gemini-flash-lite-latest",
    "gpt_model_tier2": "gemini-flash-lite-latest",
    "gpt_model_tier3": "gemini-flash-lite-latest",

    "gpt_system_prompt": (
        "당신은 반도체·IT 전문 뉴스 에디터입니다.\n"
        "주어진 뉴스 기사의 핵심 내용을 100 TOKEN 내로 간결하게 한국어로 요약해주세요.\n"
        "- 숫자, 수치, 기업명 등 구체적인 정보는 반드시 포함\n"
        "- 불필요한 수식어는 제거하고 핵심만 전달\n"
        "- 요약 외 다른 텍스트(예: \"요약:\", 설명 등)는 출력하지 말 것\n"
        "- ~습니다 체 사용해주세요"
    ),

    # 검색 테마
    "search_themes": {
        "tier1_hynix": {
            "label":         "SK하이닉스",
            "tier":          1,
            "keywords":      ["하이닉스", "SK하이닉스", "hynix", "솔리다임"],
            "tone_analysis": True,
        },
        "tier1_samsung": {
            "label":         "삼성전자",
            "tier":          1,
            "keywords":      ["삼성전자", "삼성 파운드리", "삼성 DS"],
            "tone_analysis": True,
        },
        "tier2_memory": {
            "label":         "메모리 반도체",
            "tier":          2,
            "keywords":      ["HBM", "DRAM", "D램", "NAND", "낸드"],
            "tone_analysis": False,
        },
        "tier2_ai_chip": {
            "label":         "AI 반도체",
            "tier":          2,
            "keywords":      ["엔비디아", "TSMC", "파운드리"],
            "tone_analysis": False,
        },
        "tier3_bigtech": {
            "label":         "빅테크",
            "tier":          3,
            "keywords":      ["애플", "마이크로소프트", "메타", "아마존", "구글"],
            "tone_analysis": False,
        },
        "tier3_competitor": {
            "label":         "경쟁사",
            "tier":          3,
            "keywords":      ["마이크론", "인텔"],
            "tone_analysis": False,
        },
    },

    # 관련성 필터
    "relevance_filter_enabled": True,
    "domain_blacklist": [
        "sports", "entertain", "celeb", "baseball",
        "football", "soccer", "kbo", "nba",
    ],
    "title_blacklist": [
        "야구", "축구", "농구", "배구", "골프",
        "연예", "드라마", "아이돌", "가수", "배우",
        "결혼", "이혼", "열애", "교제", "임신",
        "로또", "복권", "경마",
    ],

    # 일간 리포트
    "daily_report_enabled":  True,
    "daily_report_hour_kst": 7,
    "daily_report_top_n":    5,
}


def load_settings() -> dict:
    """
    settings.json을 읽어 DEFAULT_SETTINGS와 merge한 결과를 반환.
    파일이 없거나 손상되었으면 기본값으로 초기화.
    """
    if not config.SETTINGS_PATH.exists():
        save_settings(DEFAULT_SETTINGS)
        return dict(DEFAULT_SETTINGS)

    try:
        with open(config.SETTINGS_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except Exception as e:
        logger.warning(f"⚠️ settings.json 손상 — 기본값으로 복구: {e}")
        save_settings(DEFAULT_SETTINGS)
        return dict(DEFAULT_SETTINGS)

    # shallow merge (새 항목이 추가되어도 자동 반영)
    merged = dict(DEFAULT_SETTINGS)
    merged.update(saved)
    return merged


def save_settings(data: dict) -> None:
    """settings.json 저장."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
