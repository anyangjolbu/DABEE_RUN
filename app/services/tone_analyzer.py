"""
톤 분류 (모니터링 트랙 전용).

STEP 4A-1 + STEP-3B-11 + STEP-3B-12:
- response_mime_type="application/json"으로 JSON 강제 출력
- response_schema로 스키마 고정 (Gemini가 형식 어긋날 수 없음)
- BODY_LIMIT 2500자 유지 (1800자로 줄이면 후반부 부정 맥락이 잘려 오분류 발생)
- hostile_sentences 최대 3개 제한
- STEP-3B-11: 본문 2500자 초과 시 모니터링 대상 등장부 우선 추출 (절단 방지)
- STEP-3B-12: Gemini 호출 최대 3회 재시도 + finish_reason 진단.
              모두 실패 시 키워드 추정 대신 'LLM에러' 분류로 명시 저장
              → 추후 admin에서 재분석 가능.

분류:
    비우호    — 직접 부정 + 구조적 문제 제기 + 부정 맥락
    양호      — 사실 보도, 평이한 동향
    미분석    — Gemini가 '관련없음'으로 판정 (모니터링 대상 미등장)
    LLM에러   — Gemini 호출/파싱 N회 실패 (재분석 대상)
"""

import json
import logging
import re
from typing import Optional

from google.genai import types

from app.services.gemini_client import get_client

logger = logging.getLogger(__name__)


MONITOR_TARGETS = "SK하이닉스, 하이닉스, 솔리다임, 곽노정(SK하이닉스 대표), 최태원(SK 그룹 회장)"

# 본문 입력 한도 (토큰 절약)
BODY_LIMIT = 2500
HOSTILE_LIMIT = 3


# ── Gemini 응답 스키마 ─────────────────────────────────────────
# response_schema로 강제하면 Gemini가 이 형식을 벗어날 수 없습니다.
TONE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "classification": {
            "type": "string",
            "enum": ["비우호", "양호", "관련없음"],
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


# 모니터링 대상 키워드 (우선 추출용 — tone_analyzer 내부)
_PRIORITY_TARGETS = ("SK하이닉스", "하이닉스", "솔리다임", "곽노정", "최태원")


def _extract_relevant_section(body: str, limit: int, window: int = 800) -> str:
    """
    본문에서 모니터링 대상이 등장하는 위치 ±window 자만 추출.
    여러 등장 시 합쳐서 limit 자 이내로 압축.
    """
    spans = []  # (start, end) 쌍
    for t in _PRIORITY_TARGETS:
        idx = body.find(t)
        while idx >= 0:
            s = max(0, idx - window // 2)
            e = min(len(body), idx + len(t) + window // 2)
            spans.append((s, e))
            idx = body.find(t, e)

    if not spans:
        # 등장 없음 → 앞부분 그대로 (Gemini가 '관련없음' 판정해도 정상)
        return body[:limit]

    # 겹치는 span 병합
    spans.sort()
    merged = [spans[0]]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    # 합친 텍스트가 limit 넘으면 비례 축소
    pieces = [body[s:e] for s, e in merged]
    joined = "\n[…]\n".join(pieces)
    if len(joined) <= limit:
        return joined
    # 너무 길면 첫 등장 위주로
    return joined[:limit]


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
    if classification == "양호":
        return {"level": "양호", "tone": "중립적",
                "hostile_count": 0, "total_count": total}
    return {"level": "-", "tone": "-", "hostile_count": 0, "total_count": 0}


# ── Gemini 호출 재시도 횟수 ─────────────────────────────────────
# 1회 호출 + (RETRY_MAX-1)회 재시도. 모두 실패 시 'LLM에러' 분류.
RETRY_MAX = 3


def _llm_error_result(detail: str) -> dict:
    """Gemini 호출/파싱 N회 실패 시 명시적 LLM에러 분류로 저장."""
    return {
        "classification":    "미분석",
        "reason":            f"LLM 응답 실패: {detail}",
        "confidence":        "n/a",
        "hostile_sentences": [],
        "total_sentences":   0,
        "level":             "-",
        "tone":              "-",
        "hostile_count":     0,
        "total_count":       0,
    }


def _call_gemini(client, model: str, prompt: str) -> tuple[str, str]:
    """Gemini 호출. (raw_text, finish_reason) 반환. 빈 응답이어도 예외 없이 처리."""
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=8000,
            temperature=0,
            response_mime_type="application/json",
            response_schema=TONE_RESPONSE_SCHEMA,
        ),
    )
    finish_reason = ""
    try:
        cands = getattr(resp, "candidates", None) or []
        if cands:
            fr = getattr(cands[0], "finish_reason", None)
            finish_reason = str(fr) if fr else ""
    except Exception:
        pass
    raw = ""
    try:
        raw = (resp.text or "").strip()
    except Exception:
        # 일부 케이스에서 .text 접근 자체가 예외를 던질 수 있음
        raw = ""
    return raw, finish_reason


def _parse_response(raw: str) -> Optional[dict]:
    """Gemini raw 응답을 파싱. 실패 시 None.

    MAX_TOKENS 등으로 응답이 잘려 unterminated string이 발생한 경우,
    필수 필드(classification, confidence)가 추출되면 reason은 잘린 부분까지
    살려서 부분 복구를 시도한다.
    """
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 1차 방어: ```json ... ``` 으로 감싸서 오는 경우
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        # 2차 방어: 잘린 JSON에서 핵심 필드를 정규식으로 추출
        cls_m    = re.search(r'"classification"\s*:\s*"([^"]+)"', raw)
        conf_m   = re.search(r'"confidence"\s*:\s*"([^"]+)"', raw)
        # reason은 잘렸을 가능성이 있으므로 끝까지 비탐욕 매칭 시도
        reason_m = re.search(r'"reason"\s*:\s*"((?:[^"\\]|\\.)*)', raw)
        if cls_m:
            reason_text = reason_m.group(1) if reason_m else ""
            if reason_text:
                reason_text = reason_text + " (응답 잘림)"
            else:
                reason_text = "(응답 잘림 — 자동 복구)"
            recovered = {
                "classification":    cls_m.group(1),
                "reason":            reason_text,
                "confidence":        conf_m.group(1) if conf_m else "low",
                "hostile_sentences": [],
                "total_sentences":   0,
            }
            logger.warning("  🩹 JSON 잘림 → 핵심 필드만 복구 사용")
            return recovered
        return None


def analyze_tone(article: dict, theme_label: str, settings: dict) -> dict:
    client = get_client()
    if client is None:
        logger.warning("Gemini 미사용 — 톤 분석 스킵")
        return _empty_result("Gemini 클라이언트 미설정")

    title       = _clean(article.get("title", ""))
    description = _clean(article.get("description", ""))
    body        = article.get("_crawled_body", "")

    # 본문이 BODY_LIMIT 초과 시, 모니터링 대상 등장 부분 우선 추출
    if body and len(body) > BODY_LIMIT:
        body = _extract_relevant_section(body, BODY_LIMIT)

    model = settings.get("gpt_model_tone", "gemini-flash-lite-latest")

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

▶ "양호" — 단순 사실 보도, 평이한 동향, 실적 발표(중립적), 신제품·기술 발표,
  경쟁사 중심 기사에서 단순 비교 대상으로 짧게 언급, 통상적 경영 활동

▶ "관련없음" — 모니터링 대상이 등장하지 않거나 단순 키워드 우연 매칭

[중요 원칙]
- 한 줄이라도 모니터링 대상에 부정 영향이 있으면 비우호
- 직접 비판이 없어도 "구조적 문제의 출발점/대표 사례"로 거론되면 비우호
- 부정 단어가 있어도 결론이 긍정이면 양호
- 부정이 회사가 아닌 시장/제품 일반에 향하면 양호
- hostile_sentences는 최대 {HOSTILE_LIMIT}개까지만 인용 (가장 강한 것 우선)
- reason은 130자 이내(공백·문장부호 포함). 한국어 평문 1~2 문장으로 핵심만. 마크다운·따옴표 인용·"~합니다" 같은 군더더기 금지.

기사:
{content}"""

    # ── Gemini 호출: 최대 RETRY_MAX회 시도 ────────────────────
    parsed: Optional[dict] = None
    last_finish = ""
    last_error  = ""
    last_raw    = ""

    for attempt in range(1, RETRY_MAX + 1):
        try:
            raw, finish = _call_gemini(client, model, prompt)
            last_raw, last_finish = raw, finish
            parsed = _parse_response(raw)
            if parsed is not None:
                if attempt > 1:
                    logger.info(f"  ✅ {attempt}/{RETRY_MAX}회차 시도에서 응답 성공")
                break
            logger.warning(
                f"  ⚠️ [{attempt}/{RETRY_MAX}] 응답 파싱 실패 "
                f"(finish_reason={finish!r}, raw_len={len(raw)})"
            )
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            logger.warning(f"  ⚠️ [{attempt}/{RETRY_MAX}] 호출 예외: {last_error}")

    # ── 모두 실패 → 'LLM에러'로 명시 저장 (추후 재분석 가능) ──
    if parsed is None:
        detail = last_error or f"finish={last_finish!r} raw='{last_raw[:80]}'"
        logger.error(f"❌ {RETRY_MAX}회 모두 실패 → 'LLM에러'로 저장. {detail}")
        return _llm_error_result(detail[:200])

    # ── 응답 정규화 ──────────────────────────────────────────
    classification = str(parsed.get("classification", "")).strip()
    reason         = str(parsed.get("reason", "")).strip()
    confidence     = str(parsed.get("confidence", "medium")).strip().lower()
    hostile        = parsed.get("hostile_sentences", []) or []
    total          = int(parsed.get("total_sentences", 0) or 0)

    if not isinstance(hostile, list):
        hostile = []
    hostile = [s for s in hostile if isinstance(s, str) and s.strip()]
    hostile = hostile[:HOSTILE_LIMIT]

    if classification not in ("비우호", "양호", "관련없음"):
        # 스키마 강제 위반 → 비정상 응답으로 간주, LLM에러로 저장
        logger.error(f"  ❌ 알 수 없는 분류 '{classification}' → 'LLM에러'")
        return _llm_error_result(f"unknown classification: {classification}")

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

