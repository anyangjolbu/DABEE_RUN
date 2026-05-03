"""
settings.json 로드/저장 + 기본값 병합.

STEP 4A-1:
- search_themes를 monitor/reference 두 트랙으로 단순화
- monitor: SK하이닉스 + 임원 (톤분석 ON, 텔레그램 ON)
- reference: 경쟁사·업계 (톤분석 OFF, 본문 크롤링 OFF, 텔레그램 OFF 기본)
"""

import json
import logging
from typing import Any

from app import config

logger = logging.getLogger(__name__)


DEFAULT_SETTINGS: dict[str, Any] = {
    "schedule_interval_min": 10,

    # 네이버 API
    "naver_display_count": 30,
    "naver_sort":          "date",
    "naver_max_per_keyword": 30,

    # Gemini 모델
    "gpt_model_summary":        "gemini-flash-lite-latest",
    "gpt_model_classification": "gemini-flash-lite-latest",
    "gpt_model_tone":           "gemini-flash-latest",

    # 시스템 프롬프트 (요약용 톤)
    "summary_system_prompt": (
        "당신은 SK하이닉스 PR팀에 보고할 뉴스 요약 작성자입니다. "
        "사실 위주로 3~5문장, 핵심 숫자·인물·이슈를 포함해 작성하세요. "
        "추측이나 감정적 표현은 사용하지 마세요."
    ),

    # 검색 테마 (두 트랙)
    "search_themes": {
        "hynix_main": {
            "label":            "🔴 SK하이닉스",
            "track":            "monitor",
            "tier":             1,
            "keywords": [
                "SK하이닉스", "하이닉스", "SKhynix", "hynix", "솔리다임",
                "곽노정", "최태원",
            ],
            "tone_analysis":    True,
            "telegram_default": True,
        },
        "industry_ref": {
            "label":            "⚪ 업계 참고",
            "track":            "reference",
            "tier":             2,
            "keywords": [
                "삼성전자", "삼성DS",
                "HBM", "DRAM", "NAND",
                "엔비디아", "NVIDIA", "TSMC", "마이크론",
                "파운드리", "반도체",
            ],
            "tone_analysis":    False,
            "telegram_default": False,
        },
    },

    # 관련성 필터
    "relevance_filter_enabled": True,
    "domain_blacklist": [
        "betting", "casino", "lottery",
    ],
    "title_blacklist": [
        "야구", "축구", "골프", "올림픽", "프로야구",
        "드라마", "아이돌", "예능", "결혼", "이혼",
        "맛집", "여행", "패션", "뷰티",
    ],

    # 일간 리포트
    "daily_report_enabled":  True,
    "daily_report_time":     "08:30",
    "daily_report_max_items": 10,
}


def _settings_path() -> str:
    return str(config.SETTINGS_PATH)


def load_settings() -> dict[str, Any]:
    """settings.json을 읽어 기본값과 병합. 파일 없으면 기본값으로 생성."""
    path = _settings_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            user = json.load(f)
    except FileNotFoundError:
        logger.info(f"settings.json 없음 — 기본값으로 생성: {path}")
        save_settings(DEFAULT_SETTINGS)
        return dict(DEFAULT_SETTINGS)
    except Exception as e:
        logger.error(f"settings.json 로드 실패 ({e}) — 기본값 사용")
        return dict(DEFAULT_SETTINGS)

    # 얕은 병합: 사용자 설정 우선, 없는 키만 기본값에서 보충
    merged = dict(DEFAULT_SETTINGS)
    merged.update(user or {})

    # search_themes는 사용자가 비워두면 기본값으로 복원
    if not merged.get("search_themes"):
        merged["search_themes"] = DEFAULT_SETTINGS["search_themes"]

    return merged


def save_settings(data: dict[str, Any]) -> None:
    path = _settings_path()
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"settings.json 저장: {path}")