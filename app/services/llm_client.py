# app/services/llm_client.py
"""
OpenAI Responses API 래퍼 (STEP-COST-2).

- 기본 모델 gpt-6-luna + Flex 티어 (Standard 대비 50% 가격, 대신 느리거나
  429 Resource Unavailable 가능 — 429는 과금되지 않음)
- 구조화 출력(json_schema, strict) 전용
- 사용량 기록: llm_usage 테이블에 KST 일자별 호출·토큰·추정 비용 누적 (GET /api/admin/llm-usage)
- 일일 상한(선택): settings.llm_daily_budget_usd. 기본 null = 무제한.
  양수면 도달 시 호출하지 않고 status="budget", 0 이하면 LLM 끔.

실패는 예외 대신 LLMResult.status로 돌려준다. 호출자는 이를 보고
'미분석(재시도 대상)'으로 저장하면 된다. 기사 수집·저장·발송은
이 모듈의 결과와 무관하게 계속된다(fail-open).
"""

import json
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests

from app import config
from app.core.db import get_conn

logger = logging.getLogger(__name__)

API_URL = "https://api.openai.com/v1/responses"

DEFAULT_MODEL            = "gpt-6-luna"
DEFAULT_SERVICE_TIER     = "flex"

# Standard 티어 $/1M 토큰 (input, output). flex/batch는 50%.
PRICES = {
    "gpt-6-luna":   (0.10, 0.50),
    "gpt-5.6-luna": (0.20, 1.20),
}
_FALLBACK_PRICE = (0.20, 1.20)
_CACHED_INPUT_RATIO = 0.1          # cached input = input 단가의 10%

# 429(Flex 자원 부족·레이트리밋) 재시도 대기(초). 429는 과금되지 않는다.
_BACKOFF_429 = (2, 5)

# 상태값
#   ok          성공
#   unavailable 429 (Flex 자원 부족·레이트리밋). 과금 없음, 곧 회복 가능
#   timeout     응답 대기 초과
#   budget      일일 상한 도달 또는 상한 0(LLM 끔). 호출 안 함
#   no_key      API 키 없음. 호출 안 함
#   auth        401/403. 키 폐기·권한 문제 (전역 원인)
#   config      기타 4xx·결제 한도 소진(insufficient_quota). 모델명·파라미터 등 설정 문제 (전역 원인)
#   error       5xx 반복·응답 파싱 실패·응답 미완료 등 (기사 단위 원인일 수 있음)
GLOBAL_FAILURES = ("unavailable", "budget", "no_key", "auth", "config")


@dataclass
class LLMResult:
    status: str
    data: Optional[dict] = None
    detail: str = ""
    cost_usd: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == "ok"


# ── 일일 사용량 ──────────────────────────────────────────────

def _today() -> str:
    return datetime.now(config.KST).strftime("%Y-%m-%d")


def today_cost() -> float:
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT cost_usd FROM llm_usage WHERE day = ?", (_today(),)
            ).fetchone()
        return float(row["cost_usd"]) if row else 0.0
    except Exception as e:
        logger.warning(f"llm_usage 조회 실패(0으로 간주): {e}")
        return 0.0


def daily_budget(settings: dict) -> Optional[float]:
    """일일 상한(USD). None = 무제한(기본). 숫자가 아니거나 NaN·inf여도 무제한."""
    raw = settings.get("llm_daily_budget_usd")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def llm_disabled(settings: dict) -> bool:
    """상한을 0 이하로 넣으면 관리자가 LLM을 끈 상태."""
    budget = daily_budget(settings)
    return budget is not None and budget <= 0


def over_budget(settings: dict, share: float = 1.0) -> bool:
    """상한이 있을 때 오늘 누적 비용이 (상한 × share) 이상이거나, LLM이 꺼져 있으면 True."""
    budget = daily_budget(settings)
    if budget is None:
        return False
    if budget <= 0:
        return True
    return today_cost() >= budget * share


def _record_usage(input_tokens: int, output_tokens: int, cost: float) -> None:
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO llm_usage (day, calls, input_tokens, output_tokens, cost_usd)
                VALUES (?, 1, ?, ?, ?)
                ON CONFLICT(day) DO UPDATE SET
                    calls         = calls + 1,
                    input_tokens  = input_tokens + excluded.input_tokens,
                    output_tokens = output_tokens + excluded.output_tokens,
                    cost_usd      = cost_usd + excluded.cost_usd
                """,
                (_today(), input_tokens, output_tokens, cost),
            )
    except Exception as e:
        logger.warning(f"llm_usage 기록 실패(무시): {e}")


def usage_recent(days: int = 14) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM llm_usage ORDER BY day DESC LIMIT ?", (days,)
        ).fetchall()
    return [dict(r) for r in rows]


def _price(model: str) -> tuple[float, float]:
    """정확히 일치하지 않으면 스냅샷 이름(gpt-6-luna-2026-09-22 등)을 접두사로 매칭."""
    if model in PRICES:
        return PRICES[model]
    for name in sorted(PRICES, key=len, reverse=True):
        if model.startswith(name):
            return PRICES[name]
    return _FALLBACK_PRICE


def _estimate_cost(model: str, tier: str, usage: dict) -> float:
    pin, pout = _price(model)
    if tier in ("flex", "batch"):
        pin, pout = pin / 2, pout / 2
    in_tok  = int(usage.get("input_tokens", 0) or 0)
    cached  = int((usage.get("input_tokens_details") or {}).get("cached_tokens", 0) or 0)
    out_tok = int(usage.get("output_tokens", 0) or 0)
    return ((in_tok - cached) * pin + cached * pin * _CACHED_INPUT_RATIO + out_tok * pout) / 1e6


# ── 호출 ─────────────────────────────────────────────────────

def _parse_json(text: str) -> Optional[dict]:
    """strict 스키마 응답도 가끔 파싱에 실패해(원인 미상, 재호출 시 정상) 관대하게 읽는다.
    제어문자 허용(strict=False) → 실패 시 첫 '{'부터 객체 하나만 raw_decode."""
    try:
        return json.loads(text, strict=False)
    except ValueError:
        pass
    start = text.find("{")
    if start >= 0:
        try:
            obj, _ = json.JSONDecoder(strict=False).raw_decode(text[start:])
            return obj
        except ValueError:
            pass
    return None


def _output_text(body: dict) -> str:
    text = ""
    for item in body.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for c in item.get("content", []) or []:
            if isinstance(c, dict) and c.get("type") == "output_text":
                text += c.get("text", "")
    return text


def _error_info(resp) -> tuple[str, str]:
    """(error.code, error.message). 본문 형식이 달라도 예외 없이."""
    try:
        err = resp.json().get("error")
    except Exception:
        return "", resp.text[:150]
    if isinstance(err, dict):
        return str(err.get("code") or ""), str(err.get("message") or "")
    return "", str(err or "")


def generate_json(prompt: str, schema: dict, *, name: str, settings: dict,
                  max_output_tokens: int = 500, effort: str = "none",
                  timeout: float = 90, enforce_budget: bool = True,
                  service_tier: Optional[str] = None) -> LLMResult:
    """프롬프트 1건 → 스키마에 맞는 JSON dict. 어떤 경우에도 예외를 던지지 않는다.

    service_tier를 주면 설정값 대신 사용 ("default" = Standard 티어).
    enforce_budget=False여도 상한 0(LLM 끔)은 지킨다.
    """
    try:
        return _generate(prompt, schema, name=name, settings=settings,
                         max_output_tokens=max_output_tokens, effort=effort,
                         timeout=timeout, enforce_budget=enforce_budget,
                         service_tier=service_tier)
    except Exception as e:
        logger.error(f"❌ LLM 호출 예외 [{name}]: {e}", exc_info=True)
        return LLMResult("error", detail=f"예외: {e}"[:200])


def _generate(prompt: str, schema: dict, *, name: str, settings: dict,
              max_output_tokens: int, effort: str, timeout: float,
              enforce_budget: bool, service_tier: Optional[str]) -> LLMResult:
    if not config.OPENAI_API_KEY:
        return LLMResult("no_key", detail="OPENAI_API_KEY 미설정")
    if llm_disabled(settings):
        return LLMResult("budget", detail="LLM 비활성 (llm_daily_budget_usd ≤ 0)")
    if enforce_budget and over_budget(settings):
        return LLMResult("budget", detail=f"일일 LLM 상한 ${daily_budget(settings):.2f} 도달")

    model = settings.get("llm_model") or DEFAULT_MODEL
    tier  = service_tier or settings.get("llm_service_tier") or DEFAULT_SERVICE_TIER
    payload = {
        "model": model,
        "input": prompt,
        "max_output_tokens": max_output_tokens,
        "reasoning": {"effort": effort},
        "text": {"format": {"type": "json_schema", "name": name,
                            "schema": schema, "strict": True}},
    }
    if tier and tier != "default":
        payload["service_tier"] = tier
    headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}",
               "Content-Type": "application/json"}

    resp = None
    for attempt in range(len(_BACKOFF_429) + 1):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload,
                                 timeout=(10, timeout))
        except requests.exceptions.Timeout:
            return LLMResult("timeout", detail=f"{timeout:.0f}s 초과")
        except requests.exceptions.RequestException as e:
            return LLMResult("error", detail=f"요청 예외: {e}"[:200])

        if resp.status_code == 429:
            code, msg = _error_info(resp)
            if code == "insufficient_quota":     # 결제 한도 소진 → 재시도 무의미
                logger.error(f"❌ OpenAI 결제 한도 소진 [{name}]: {msg[:150]}")
                return LLMResult("config", detail=f"insufficient_quota: {msg[:150]}")
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt < len(_BACKOFF_429):
                time.sleep(_BACKOFF_429[attempt])
                continue
            status = "unavailable" if resp.status_code == 429 else "error"
            return LLMResult(status, detail=f"HTTP {resp.status_code}: {resp.text[:150]}")
        break

    if resp.status_code != 200:
        code, msg = _error_info(resp)
        logger.error(f"❌ OpenAI {resp.status_code} [{name}]: {msg[:200]}")
        # 401/403: 키 문제, 그 밖의 4xx: 모델명·파라미터 등 설정 문제. 둘 다 과금 없음·전역 원인
        status = "auth" if resp.status_code in (401, 403) else "config"
        return LLMResult(status, detail=f"HTTP {resp.status_code}: {msg[:150]}")

    try:
        body = resp.json()
    except ValueError:
        return LLMResult("error", detail="HTTP 200: 응답 JSON 아님")
    if not isinstance(body, dict):
        return LLMResult("error", detail="HTTP 200: 응답 형식 이상")

    usage = body.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    actual_tier = body.get("service_tier") or tier
    cost = _estimate_cost(str(body.get("model") or model), actual_tier, usage)
    _record_usage(int(usage.get("input_tokens", 0) or 0),
                  int(usage.get("output_tokens", 0) or 0), cost)

    if body.get("status") != "completed":
        reason = (body.get("incomplete_details") or {}).get("reason", body.get("status"))
        return LLMResult("error", detail=f"응답 미완료: {reason}", cost_usd=cost)

    text = _output_text(body).strip()
    data = _parse_json(text)
    if not isinstance(data, dict):
        logger.warning(f"LLM JSON 파싱 실패 [{name}] len={len(text)} raw={text[:300]!r}")
        return LLMResult("error", detail=f"JSON 파싱 실패(len={len(text)})", cost_usd=cost)
    return LLMResult("ok", data=data, cost_usd=cost)
