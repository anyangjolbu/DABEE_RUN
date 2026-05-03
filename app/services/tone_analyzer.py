"""
톤 분류 (모니터링 트랙 전용).

STEP 4A-1 + 핫픽스 2:
- response_mime_type="application/json"으로 JSON 강제 출력
- response_schema로 스키마 고정 (Gemini가 형식 어긋날 수 없음)
- 본문 2500자 → 1800자로 단축 (토큰 절약)
- hostile_sentences 최대 3개 제한
- max_output_tokens 1500 → 2000

분류:
    비우호 — 직접 부정 + 구조적 문제 제기 + 부정 맥락
    일반   — 사실 보도, 평이한 동향
    미분석 — Gemini 호출 실패, 응답 깨짐, 관련없음
"""

import json
import logging
import re

from google.genai import types

from app.services.gemini_client import get_client

logger = logging.getLogger(__name__)


MONITOR_TARGETS = "SK하이닉스, 하이닉스, 솔리다임, 곽노정(SK하이닉스 대표), 최태원(SK 그룹 회장)"

# 본문 입력 한도 (토큰 절약)
BODY_LIMIT = 1800
HOSTILE_LIMIT = 3


# ── Gemini 응답 스키마 ─────────────────────────────────────────
# response_schema로 강제하면 Gemini가 이 형식을 벗어날 수 없습니다.
TONE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "classification": {
            "type": "string",
            "enum": ["비우호", "일반", "관련없음"],
        },
        "reason": {
            "type": "string",
        },
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
        },
        "hostile_sentences": {
            "type": "array",
            "items": {"type": "string"},
        },
        "total_sentences": {
            "type": "integer",
        },
    },
    "required": ["classification", "reason", "confidence",
                 "hostile_sentences", "total_sentences"],
}


def _clean(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _empty_result(reason: str = "분석 안 됨") -> dict:
    return {
        "classification":    "미분석",
        "reason":            reason,
        "confidence":        "low",
        "hostile_sentences": [],
        "total_sentences":   0,
        "level":             "-",
        "tone":              "-",
        "hostile_count":     0,
        "total_count":       0,
    }


def _build_legacy_fields(classification: str, hostile: list, total: int) -> dict:
    if classification == "비우호":
        return {"level": "경고", "tone": "비우호적",
                "hostile_count": len(hostile), "total_count": total}
    if classification == "일반":
        return {"level": "양호", "tone": "중립적",
                "hostile_count": 0, "total_count": total}
    return {"level": "-", "tone": "-", "hostile_count": 0, "total_count": 0}


def analyze_tone(article: dict, theme_label: str, settings: dict) -> dict:
    client = get_client()
    if client is None:
        logger.warning("Gemini 미사용 — 톤 분석 스킵")
        return _empty_result("Gemini 클라이언트 미설정")

    title       = _clean(article.get("title", ""))
    description = _clean(article.get("description", ""))
    body        = article.get("_crawled_body", "")

    model = settings.get("gpt_model_tone", "gemini-flash-latest")

    if body:
        content = f"제목: {title}\n\n본문:\n{body[:BODY_LIMIT]}"
        logger.info(f"  📊 톤분류(본문 {min(len(body), BODY_LIMIT)}자), model={model}")
    else:
        content = f"제목: {title}\n\n요약: {description}"
        logger.info(f"  📊 톤분류(description), model={model}")

    prompt = f"""다음 기사가 SK하이닉스 PR팀 관점에서 어떻게 보이는지 평가하시오.

[모니터링 대상]
{MONITOR_TARGETS}

[분류 기준]

▶ "비우호" — 다음 중 하나라도 해당:
1. 직접 부정 신호 — 실적 악화, 주가 하락, 소송, 제재, 노사 갈등, 파업,
   기술 열위, 점유율 하락, 신용등급 하락, 임원 도덕성·법적 문제
2. 구조적 문제 제기 — SK/SK하이닉스에서 시작된 사회적 갈등 다루는 칼럼·사설,
   하청·임금 격차로 SK하이닉스 거론, 산업·노동 비판 사례로 거론,
   곽노정·최태원의 경영·리더십에 대한 부정적 평가
3. 부정 맥락 연관 — 업계 위기 기사에서 주요 사례로 언급, 경쟁사 대비 불리한 비교

▶ "일반" — 단순 사실 보도, 평이한 동향, 실적 발표(중립적), 신제품·기술 발표,
  경쟁사 중심 기사에서 단순 비교 대상으로 짧게 언급, 통상적 경영 활동

▶ "관련없음" — 모니터링 대상이 등장하지 않거나 단순 키워드 우연 매칭

[중요 원칙]
- 한 줄이라도 모니터링 대상에 부정 영향이 있으면 비우호
- 직접 비판이 없어도 "구조적 문제의 출발점/대표 사례"로 거론되면 비우호
- 부정 단어가 있어도 결론이 긍정이면 일반
- 부정이 회사가 아닌 시장/제품 일반에 향하면 일반
- hostile_sentences는 최대 {HOSTILE_LIMIT}개까지만 인용 (가장 강한 것 우선)

기사:
{content}"""

    raw = ""
    try:
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=2000,
                temperature=0,
                response_mime_type="application/json",
                response_schema=TONE_RESPONSE_SCHEMA,
            ),
        )
        raw = (resp.text or "").strip()

        # response_mime_type="application/json"이면 raw가 깨끗한 JSON
        parsed = json.loads(raw)

        classification = str(parsed.get("classification", "")).strip()
        reason         = str(parsed.get("reason", "")).strip()
        confidence     = str(parsed.get("confidence", "medium")).strip().lower()
        hostile        = parsed.get("hostile_sentences", []) or []
        total          = int(parsed.get("total_sentences", 0) or 0)

        if not isinstance(hostile, list):
            hostile = []
        hostile = [s for s in hostile if isinstance(s, str) and s.strip()]
        hostile = hostile[:HOSTILE_LIMIT]

        if classification not in ("비우호", "일반", "관련없음"):
            logger.warning(f"  ⚠️ 알 수 없는 분류 '{classification}' → 미분석")
            return _empty_result(f"알 수 없는 분류: {classification}")

        if classification == "관련없음":
            result = _empty_result(reason or "모니터링 대상이 등장하지 않음")
            result["total_sentences"] = total
            result["total_count"]     = total
            result["confidence"]      = confidence if confidence in ("high","medium","low") else "medium"
            logger.info(f"  📊 결과: [관련없음] {result['reason'][:50]}")
            return result

        if confidence not in ("high", "medium", "low"):
            confidence = "medium"

        legacy = _build_legacy_fields(classification, hostile, total)
        result = {
            "classification":    classification,
            "reason":            reason,
            "confidence":        confidence,
            "hostile_sentences": hostile,
            "total_sentences":   total,
            **legacy,
        }
        logger.info(
            f"  📊 결과: [{classification}/{confidence}] "
            f"비우호문장 {len(hostile)}/{total} | {reason[:50]}"
        )
        return result

    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON 파싱 실패: {e} | raw='{raw[:200]}'")
        return _empty_result(f"JSON 파싱 실패")
    except Exception as e:
        logger.error(f"❌ 톤 분류 실패: {e} | raw='{raw[:200]}'")
        return _empty_result(f"분류 실패: {type(e).__name__}")