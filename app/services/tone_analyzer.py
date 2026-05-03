# app/services/tone_analyzer.py
"""
비우호 문장 감지 (TIER 1 전용).

PR팀 입장에서 "회사에 부정적인 문장이 어떤 것이고 몇 개냐"는
가장 중요한 정보입니다. 단순히 우호/비우호 라벨만 주는 게 아니라
실제 비우호 문장 원문까지 추출해 텔레그램·리포트에서 인용합니다.

판정 기준:
    양호 — 비우호 문장 0개
    주의 — 비우호 문장 1개
    경고 — 비우호 문장 2개 이상

반환 형식 (dict):
    {
        "level":             "양호" | "주의" | "경고",
        "tone":              "우호적" | "중립적" | "비우호적",
        "hostile_count":     int,
        "total_count":       int,        # 기사 전체 문장 수
        "hostile_sentences": [str, ...]  # 비우호 문장 원문
    }
"""

import json
import logging
import re

from google.genai import types

from app.services.gemini_client import get_client

logger = logging.getLogger(__name__)


# ── 회사명 정규화 ────────────────────────────────────────────────────
# settings의 theme label은 이모지·공백이 섞여 있어서 "🔴 SK하이닉스"가
# 들어옵니다. 이를 GPT가 명확히 이해할 수 있는 표준명으로 변환.
COMPANY_ALIASES = {
    "삼성파운드리": "삼성전자",
    "삼성DS":       "삼성전자",
    "삼성전자":     "삼성전자",
    "SK하이닉스":   "SK하이닉스",
    "SKhynix":      "SK하이닉스",
    "하이닉스":     "SK하이닉스",
}


def _clean(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _normalize_company(company: str) -> str:
    """label에서 이모지·공백 제거 후 표준명으로 매핑."""
    raw = re.sub(r"[🔴🟠🟡⚪⚫🟢🔵🟣🟤\s]", "", company or "")
    raw_compact = raw.replace(" ", "")
    for key, val in COMPANY_ALIASES.items():
        if key in raw_compact:
            return val
    return raw or "해당 기업"


def _empty_result() -> dict:
    """오류·키 누락 시 안전하게 반환할 기본값."""
    return {
        "level":             "양호",
        "tone":              "-",
        "hostile_count":     0,
        "total_count":       0,
        "hostile_sentences": [],
    }


def _level_from_count(h_count: int) -> tuple[str, str]:
    """비우호 문장 수 → (level, tone) 변환."""
    if h_count == 0:
        return "양호", "우호적"
    if h_count == 1:
        return "주의", "중립적"
    return "경고", "비우호적"


def analyze_tone(article: dict, company: str, settings: dict) -> dict:
    """
    기사에서 특정 회사에 대한 비우호 문장을 추출.

    Args:
        article: 기사 dict (title, description, _crawled_body 사용)
        company: 분석 대상 회사명 (theme label도 OK — 자동 정규화)
        settings: settings.json (모델 선택용)

    Returns:
        결과 dict (위 모듈 docstring 참고).
    """
    client = get_client()
    if client is None:
        logger.warning("Gemini 미사용 — 톤 분석 스킵")
        return _empty_result()

    title       = _clean(article.get("title", ""))
    description = _clean(article.get("description", ""))
    body        = article.get("_crawled_body", "")
    company_n   = _normalize_company(company)

    # TIER 1 전용이므로 항상 tier1 모델 사용
    model = settings.get("gpt_model_tier1", "gemini-flash-lite-latest")

    # 본문 있으면 본문, 없으면 description
    if body:
        content = f"제목: {title}\n\n본문:\n{body[:2500]}"
        logger.info(f"  📊 톤분석(본문 {len(body)}자): {company_n}, model={model}")
    else:
        content = f"제목: {title}\n\n요약: {description}"
        logger.info(f"  📊 톤분석(description): {company_n}, model={model}")

    prompt = f"""다음 기사에서 '{company_n}'에 대해 비우호적인 문장을 찾아라.

[비우호적 문장 정의]
'{company_n}'에 직접적으로 부정적 영향을 주는 문장:
- 실적 악화, 매출 감소, 영업손실, 주가 하락
- 소송, 제재, 규제, 조사, 과징금
- 파업, 노사 갈등, 인력 감축
- 기술 열위, 경쟁 패배, 시장점유율 하락
- 리콜, 품질 결함, 사고
- 신용등급 하락, 유동성 위기

[제외 조건 — 비우호로 분류하지 말 것]
- '{company_n}'이 주어/목적어가 아닌 문장
- 경쟁사·업계 전반의 부정적 내용 ('{company_n}' 직접 언급 없는 것)
- 반론·인용으로 등장하는 소수 의견
- 부정어가 있어도 결론이 긍정인 문장 (예: "우려를 불식", "위기를 극복")

[출력 형식 — 반드시 아래 JSON만 출력, 다른 텍스트 없이]
{{
  "total_sentences": <기사 전체 문장 수 (정수)>,
  "hostile_sentences": [
    "<비우호적 문장 원문 그대로>",
    "<비우호적 문장 원문 그대로>"
  ]
}}

비우호적 문장이 없으면:
{{
  "total_sentences": <정수>,
  "hostile_sentences": []
}}

기사:
{content}"""

    raw = ""
    try:
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=800,
                temperature=0,    # 일관성 최우선
            ),
        )
        raw = (resp.text or "").strip()

        # 응답에서 JSON 블록 추출 (```json ... ``` 같은 래퍼 제거)
        cleaned = re.sub(r"```(?:json)?", "", raw).strip().strip("`")
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not m:
            raise ValueError("JSON 블록을 찾지 못함")

        parsed  = json.loads(m.group())
        total   = int(parsed.get("total_sentences", 0))
        hostile = parsed.get("hostile_sentences", []) or []

        if not isinstance(hostile, list):
            hostile = []

        # 회사명이 실제로 등장하지 않는 문장은 거르기 (Gemini 환각 방지)
        hostile = [s for s in hostile if isinstance(s, str) and s.strip()]

        h_count = len(hostile)
        level, tone = _level_from_count(h_count)

        result = {
            "level":             level,
            "tone":              tone,
            "hostile_count":     h_count,
            "total_count":       total,
            "hostile_sentences": hostile,
        }
        logger.info(f"  📊 결과: [{level}] 비우호 {h_count}/{total}문장")
        return result

    except Exception as e:
        logger.error(f"❌ 톤 분석 실패: {e} | raw='{raw[:200]}'")
        return _empty_result()
