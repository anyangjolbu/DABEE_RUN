"""
톤 분류 (모니터링 트랙 전용).

STEP-COST-2 (Gemini → OpenAI gpt-6-luna Flex):
- 사전 규칙: 제목·description·본문 어디에도 모니터링 대상이 없으면
  LLM 호출 없이 '미분석'(재분석 제외)으로 확정. LLM도 '관련없음'을 줄 기사.
- 프롬프트 최소화 + 비우호일 때만 근거·인용문 출력 (양호는 빈 값)
- 본문 BODY_LIMIT 2500자 유지 (1800자로 줄이면 후반부 부정 맥락이 잘려
  오분류 발생 — STEP-3B-11), 초과 시 대상 등장부 우선 추출
- LLM 실패(Flex 429·타임아웃·예산 초과 등)는 '미분석' + retryable 로 돌려주고,
  재분석(reanalyze)이 나중에 다시 시도한다. 발송은 분류와 무관하게 진행.

분류:
    비우호 — 대상에게 불리한 내용이 조금이라도 있음
    양호   — 사실 보도, 평이한 동향
    미분석 — 대상 미등장(final) 또는 LLM 실패(retryable)
"""

import logging
import re

from app.services import llm_client

logger = logging.getLogger(__name__)


# 사전 규칙·본문 추출용 모니터링 대상 (소문자 비교)
_PRIORITY_TARGETS = ("sk하이닉스", "하이닉스", "skhynix", "sk hynix", "hynix",
                     "솔리다임", "곽노정", "최태원")

# 본문 입력 한도
BODY_LIMIT = 2500

TONE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "label":  {"type": "string", "enum": ["비우호", "양호", "관련없음"]},
        "reason": {"type": "string"},
        "quote":  {"type": "string"},
    },
    "required": ["label", "reason", "quote"],
}

PROMPT = """SK하이닉스 PR팀 관점에서 기사 톤을 분류하라.
대상: SK하이닉스(솔리다임 포함), 곽노정 대표, 최태원 회장
- 비우호: 대상에게 불리한 내용이 조금이라도 있음 (실적·주가 하락, 소송·제재·노사갈등, 기술·점유율 열위, 경영진 비판·논란, 부정적 이슈의 사례로 거론, 경쟁사 대비 불리한 비교)
- 양호: 불리한 내용 없음 (사실 보도·동향·발표)
- 관련없음: 대상이 기사에 나오지 않음
비우호일 때만 reason(60자 이내)과 quote(가장 부정적인 문장 1개)를 쓰고, 아니면 둘 다 빈 문자열.

제목: {title}
본문:
{body}"""


def _clean(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def has_monitor_target(*texts: str) -> bool:
    haystack = " ".join(t or "" for t in texts).lower()
    return any(t in haystack for t in _PRIORITY_TARGETS)


def _extract_relevant_section(body: str, limit: int, window: int = 800) -> str:
    """
    본문에서 모니터링 대상이 등장하는 위치 ±window/2 자만 추출.
    여러 등장 시 합쳐서 limit 자 이내로 압축.
    """
    lower = body.lower()
    spans = []
    for t in _PRIORITY_TARGETS:
        idx = lower.find(t)
        while idx >= 0:
            s = max(0, idx - window // 2)
            e = min(len(body), idx + len(t) + window // 2)
            spans.append((s, e))
            idx = lower.find(t, e)

    if not spans:
        return body[:limit]

    spans.sort()
    merged = [spans[0]]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    joined = "\n[…]\n".join(body[s:e] for s, e in merged)
    return joined[:limit]


def _result(classification: str, reason: str, *, hostile: list | None = None,
            confidence: str = "", final: bool = False, retryable: bool = False,
            llm_status: str = "") -> dict:
    hostile = hostile or []
    if classification == "비우호":
        legacy = {"level": "경고", "tone": "비우호적", "hostile_count": len(hostile)}
    elif classification == "양호":
        legacy = {"level": "양호", "tone": "중립적", "hostile_count": 0}
    else:
        legacy = {"level": "-", "tone": "-", "hostile_count": 0}
    return {
        "classification":    classification,
        "reason":            reason,
        "confidence":        confidence,
        "hostile_sentences": hostile,
        "total_sentences":   0,
        "total_count":       0,
        "final":             final,       # True → 재분석 대상에서 영구 제외
        "retryable":         retryable,   # True → 재분석이 나중에 재시도
        "llm_status":        llm_status,  # retryable 사유 (llm_client.LLMResult.status)
        **legacy,
    }


def analyze_tone(article: dict, theme_label: str, settings: dict,
                 allow_llm: bool = True) -> dict:
    title       = _clean(article.get("title", ""))
    description = _clean(article.get("description", ""))
    body        = article.get("_crawled_body", "") or ""

    # ── 사전 규칙: 대상 미등장 → LLM 호출 없이 확정 ─────────────
    if not has_monitor_target(title, description, body):
        logger.info("  📊 톤분류 생략: 모니터링 대상 미등장")
        return _result("미분석", "모니터링 대상 미등장", confidence="n/a", final=True)

    if not allow_llm:
        return _result("미분석", "LLM 대기: 사이클 시간 초과", confidence="n/a",
                       retryable=True, llm_status="deferred")

    if len(body) > BODY_LIMIT:
        body = _extract_relevant_section(body, BODY_LIMIT)
    if not body:
        body = description

    prompt = PROMPT.format(title=title, body=body[:BODY_LIMIT])
    res = llm_client.generate_json(prompt, TONE_SCHEMA, name="tone",
                                   settings=settings, max_output_tokens=500)
    if res.status == "unavailable":
        # Flex 자원 부족(429, 과금 없음) → 이 기사만 Standard로 1회 재시도.
        # 텔레그램에 '미분석'으로 나가 비우호 신호가 빠지는 일을 줄인다 (예산 상한은 그대로 적용).
        logger.info("  ↪ Flex 혼잡 → Standard 티어로 재시도")
        res = llm_client.generate_json(prompt, TONE_SCHEMA, name="tone",
                                       settings=settings, max_output_tokens=500,
                                       service_tier="default")
    if not res.ok:
        logger.warning(f"  ⚠️ 톤분류 보류({res.status}): {res.detail[:120]}")
        return _result("미분석", f"LLM 대기: {res.status}", confidence="n/a",
                       retryable=True, llm_status=res.status)

    label  = str(res.data.get("label", "")).strip()
    reason = str(res.data.get("reason", "")).strip()
    quote  = str(res.data.get("quote", "")).strip()

    if label == "관련없음":
        logger.info("  📊 결과: [관련없음]")
        return _result("미분석", reason or "모니터링 대상 미등장(LLM 판정)",
                       confidence="n/a", final=True)
    if label not in ("비우호", "양호"):
        return _result("미분석", f"LLM 대기: unknown label {label!r}",
                       confidence="n/a", retryable=True, llm_status="error")

    if label == "양호":
        reason, quote = "", ""
    result = _result(label, reason, hostile=[quote] if quote else [])
    logger.info(f"  📊 결과: [{label}] {reason[:50]}")
    return result
