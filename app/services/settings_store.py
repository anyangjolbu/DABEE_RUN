"""
settings.json 로드/저장 + 기본값 병합.

STEP 4A-1:
- search_themes를 monitor/reference 두 트랙으로 단순화
- monitor: SK하이닉스 직접 (톤분석 + 텔레그램)
- reference: 경쟁사·업계 (본문에 SK등장 시 monitor로 자동 승격)

STEP-3B-13:
- tier/tone_analysis 필드 제거. 분기 기준은 track 단일.
- schedule_interval_min과 schedule_interval_minutes 둘 다 인식 (scheduler.py 호환).
"""

import json
import logging
from typing import Any

from app import config

logger = logging.getLogger(__name__)


DEFAULT_SETTINGS: dict[str, Any] = {
    "schedule_interval_minutes": 10,
    "article_expire_hours":      24,

    # 네이버 API
    "naver_display_count": 30,
    "naver_sort":          "date",

    # Gemini 모델 (STEP-3B-34: 요약은 lite, 톤분석은 flash로 차등 유지)
    "gpt_model_summary": "gemini-flash-lite-latest",
    "gpt_model_tone":    "gemini-flash-latest",

    # 시스템 프롬프트 (요약용 톤)
    "summary_system_prompt": (
        "당신은 SK하이닉스 PR팀에 보고할 뉴스 요약 작성자입니다. "
        "사실 위주로 3~5문장, 핵심 숫자·인물·이슈를 포함해 작성하세요. "
        "추측이나 감정적 표현은 사용하지 마세요."
    ),

    # 검색 테마 (두 트랙)
    "search_themes": {
        "hynix_main": {
            "label":  "🔴 SK하이닉스",
            "track":  "monitor",
            "keywords": [
                "SK하이닉스", "하이닉스", "SKhynix", "hynix", "솔리다임",
                "곽노정", "최태원",
            ],
        },
        "industry_ref": {
            "label":  "⚪ 업계 참고",
            "track":  "reference",
            "keywords": [
                "삼성전자", "삼성DS",
                "HBM", "DRAM", "NAND",
                "엔비디아", "NVIDIA", "TSMC", "마이크론",
                "파운드리", "반도체",
            ],
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


_PRIORITY_HINTS = (
    "sk하이닉스", "하이닉스", "skhynix", "hynix", "솔리다임", "곽노정", "최태원",
)


def _infer_track(theme_id: str, theme: dict) -> str:
    """track 필드 누락 테마의 track 추론.

    1) keywords에 SK하이닉스 핵심 키워드가 있으면 monitor
    2) theme_id에 'hynix'/'sk' 단서가 있으면 monitor
    3) 그 외(tier1_samsung, tier3_bigtech 등 경쟁사/업계) → reference
    """
    keywords_lower = [str(k).lower() for k in theme.get("keywords", [])]
    if any(h in kw for h in _PRIORITY_HINTS for kw in keywords_lower):
        return "monitor"
    tid_lower = (theme_id or "").lower()
    if "hynix" in tid_lower or tid_lower.endswith("_sk") or tid_lower.startswith("sk"):
        return "monitor"
    return "reference"


def _backfill_themes_track(themes: dict) -> bool:
    """track이 비어있는 테마에 자동 채움. 변경 발생 시 True."""
    changed = False
    for tid, theme in themes.items():
        if not isinstance(theme, dict):
            continue
        if theme.get("track") in ("monitor", "reference"):
            continue
        inferred = _infer_track(tid, theme)
        theme["track"] = inferred
        changed = True
        logger.info(f"  🔧 [{tid}] track 자동 추론 → {inferred}")
    return changed


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

    # track 필드 자동 백필 (구 settings.json 호환)
    if _backfill_themes_track(merged["search_themes"]):
        save_settings(merged)
        logger.info("✅ track 백필 완료 — settings.json 갱신")

    return merged


def save_settings(data: dict[str, Any]) -> None:
    path = _settings_path()
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"settings.json 저장: {path}")