# app/services/report_impact.py
"""
일간 리포트 임팩트 평가 모듈.

LLM 1회 호출로 다음 3가지를 동시에 선정:
1. 톱5 PR 코멘터리 (marker_count 1~5, comment 2~4문장)
2. 당사·그룹 톱10 (score 0~100)
3. 업계동향 톱10 (score 0~100)

응답은 strict JSON. 파싱 실패 시 fallback (시간순 컷).
"""

import json
import logging
import re
import time
from typing import Optional

from google.genai import types

from app.services.gemini_client import get_client

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-flash-latest"
MAX_OUTPUT_TOKEN = 8192
RETRY_MAX = 3
RETRY_DELAY = 2

DEFAULT_IMPACT_PROMPT = """당신은 SK하이닉스 곽노정 CEO입니다. 오늘 아침 비서가 신문 스크랩 수백 건을 책상 위에 올렸고, 당신은 그 중 가장 먼저 읽을 5건을 직접 골라야 합니다.

[당신이 첫 번째로 펼칠 기사의 조건]
당신이 가장 먼저 펼치는 기사는 거시 경제 지표(코스피·환율·수출 통계)나 경쟁사 실적(삼성전자·마이크론·TSMC)이 아닙니다. 당신이 책임지는 회사(SK하이닉스), 당신이 속한 그룹(SK), 그리고 당신 직위(CEO)에 직접 영향을 주는 기사입니다.

[CEO 관점 점수 산출] 각 기사를 다음 세 축으로 평가하세요.
A. "이 뉴스의 주인공이 SK하이닉스 또는 SK 그룹사인가?" (0~40점)
   - SK하이닉스가 주체: 40점
   - SK 그룹사·임원(최태원 등)이 주체: 25점
   - 업계 일반·경쟁사·거시 지표: 0~10점

B. "내(CEO) 의사결정·발표·해명에 영향을 주는가?" (0~30점)
   - 즉시 대응 필요: 30점
   - 향후 참고용: 10점
   - 영향 없음: 0점

C. "오늘 임직원·주주·기자가 나에게 직접 질문할 가능성?" (0~30점)
   - 모두 질문할 사안: 30점
   - 일부 질문 가능: 15점
   - 질문 없음: 0점

총점 = A + B + C (최대 100점)

[잘못된 선정 예시 - 절대 따라하지 말 것]
× rank_1: "코스피 7000 돌파" → 거시 지표일 뿐 우리 회사 주인공 아님. (A=5, B=0, C=10 = 15점)
× rank_1: "삼성전자 시총 1조 달러" → 경쟁사 뉴스, 우리 임팩트 없음. (A=5, B=0, C=10 = 15점)
× rank_2: "한국 수출 일본 추월" → 산업 일반론. (A=10, B=5, C=10 = 25점)

[올바른 선정 예시]
✓ rank_1: "SK하이닉스 1Q 영업익 37조" → 우리 회사 핵심 실적. (A=40, B=30, C=30 = 100점)
✓ rank_2: "곽노정 사장 자사주 94억 수령" → CEO 본인 동향. (A=40, B=10, C=30 = 80점)
✓ rank_3: "최태원 회장에 전남 팹 설립 요청" → 그룹 회장 액션. (A=25, B=25, C=20 = 70점)

자사 기사가 0건일 때만 그룹·업계 기사가 rank_1을 차지할 수 있습니다. 자사 기사가 1건이라도 있으면 그것이 rank_1입니다.

[입력 형식] 각 기사: ID|카테고리|언론사|제목|요약
- 카테고리: company_group(SK 그룹 직접 관련) 또는 industry(업계 동향)

[작업 1] top5_commentary - rank_1 ~ rank_5 (필수, 모두 채울 것)
- 위 점수 산출에 따라 총점 높은 순으로 5건 선정
- 각 필드는 article_id(입력 ID 중 하나), comment(2~4문장 PR 분석)를 포함
- comment 끝에 자기 채점 표시 필수: " (A점+B점+C점=총점)" 형식
  예: "...전망입니다. (A40+B30+C30=100)"
- comment는 "CEO에게 보고하는 톤"으로 작성 (예: "...로 분석됩니다", "...에 대한 대응이 필요합니다")

[작업 2] company_group_top10 - 당사·그룹 톱10
- category=company_group 기사 중 임팩트 상위 10건 (입력에 충분하면 정확히 10건)
- 같은 사건 중복 보도 시 메이저 언론사 1건만 선정 후 다른 주제로 채울 것
- score: 0~100 정수, 기사마다 차등을 두어 다양화

[작업 3] industry_top10 - 업계동향 톱10
- category=industry 기사 중 임팩트 상위 10건 (입력에 충분하면 정확히 10건)
- 메이저 언론사 + [단독] 키워드는 가산점
- 같은 사건 중복 보도 시 1건만 선정
- score: 0~100 정수, 기사마다 차등

[출력 형식] 아래 정확한 구조의 단일 JSON 객체로만 응답하세요.
{
  "top5_commentary": {
    "rank_1": {"article_id": <int>, "comment": "<2-4문장> (A?+B?+C?=총점)"},
    "rank_2": {"article_id": <int>, "comment": "<2-4문장> (A?+B?+C?=총점)"},
    "rank_3": {"article_id": <int>, "comment": "<2-4문장> (A?+B?+C?=총점)"},
    "rank_4": {"article_id": <int>, "comment": "<2-4문장> (A?+B?+C?=총점)"},
    "rank_5": {"article_id": <int>, "comment": "<2-4문장> (A?+B?+C?=총점)"}
  },
  "company_group_top10": [{"article_id": <int>, "score": <0-100>}],
  "industry_top10": [{"article_id": <int>, "score": <0-100>}]
}

article_id는 반드시 입력에 등장한 ID만 사용. 톱10은 입력 부족 시 가능한 만큼만 채워도 되지만, top5_commentary의 rank_1~rank_5는 절대 빠뜨리지 마시오.
"""


def _is_transient(err: Exception) -> bool:
    s = str(err).lower()
    return any(k in s for k in ("503", "unavailable", "429", "resource_exhausted",
                                 "deadline_exceeded", "timeout"))


def _build_prompt(articles: list[dict], categories: dict[int, str], system_prompt: str) -> str:
    """기사 목록을 LLM 입력 텍스트로 직렬화."""
    lines = [system_prompt, "", "[기사 목록]"]
    for a in articles:
        aid = a.get("id")
        cat = categories.get(aid, "industry")
        press = a.get("press") or ""
        title = (a.get("title_clean") or a.get("title") or "").replace("|", "/")[:120]
        summary = (a.get("summary") or "").replace("|", "/")[:200]
        lines.append(f"{aid}|{cat}|{press}|{title}|{summary}")
    return "\n".join(lines)


def _extract_json(text: str) -> Optional[dict]:
    """LLM 응답에서 JSON 추출. 마크다운 코드블록 제거. 배열 응답도 처리."""
    if not text:
        return None
    t = text.strip()
    # ```json ... ``` 제거
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    parsed = None
    try:
        parsed = json.loads(t)
    except json.JSONDecodeError:
        # 첫 { 또는 [ 부터 마지막 } 또는 ] 까지 추출 시도
        for open_c, close_c in (("{", "}"), ("[", "]")):
            start = t.find(open_c)
            end = t.rfind(close_c)
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(t[start:end+1])
                    break
                except json.JSONDecodeError:
                    continue
    if parsed is None:
        return None
    # 배열로 응답한 경우 — 우리 스키마가 아니므로 fallback 신호로 None 반환
    if isinstance(parsed, list):
        logger.warning(f"⚠️ LLM이 배열로 응답 (객체 기대) — 항목 {len(parsed)}개")
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _validate(payload: dict, valid_ids: set[int]) -> dict:
    """응답 검증 + 정제. 잘못된 ID/형식 제거."""
    out = {
        "top5_commentary": [],
        "company_group_top10": [],
        "industry_top10": [],
    }
    top5_obj = payload.get("top5_commentary", {})
    if isinstance(top5_obj, list):
        # 구버전 호환: 배열로 와도 순서대로 marker 부여
        for i, c in enumerate(top5_obj[:5], start=1):
            try:
                aid = int(c["article_id"])
                comment = str(c.get("comment", "")).strip()
                if aid in valid_ids and comment:
                    out["top5_commentary"].append({
                        "article_id": aid, "marker_count": i, "comment": comment,
                    })
            except (KeyError, ValueError, TypeError):
                continue
    else:
        for i in range(1, 6):
            item = top5_obj.get(f"rank_{i}")
            if not isinstance(item, dict):
                continue
            try:
                aid = int(item["article_id"])
                comment = str(item.get("comment", "")).strip()
                if aid in valid_ids and comment:
                    out["top5_commentary"].append({
                        "article_id": aid, "marker_count": i, "comment": comment,
                    })
            except (KeyError, ValueError, TypeError):
                continue

    for key in ("company_group_top10", "industry_top10"):
        seen_ids = set()
        for c in payload.get(key, [])[:10]:
            try:
                aid = int(c["article_id"])
                score = int(c["score"])
                if aid in valid_ids and 0 <= score <= 100 and aid not in seen_ids:
                    out[key].append({"article_id": aid, "score": score})
                    seen_ids.add(aid)
            except (KeyError, ValueError, TypeError):
                continue
        out[key].sort(key=lambda x: -x["score"])
    return out


def _fallback(articles: list[dict], categories: dict[int, str]) -> dict:
    """LLM 실패 시 단순 fallback: 시간 역순으로 컷."""
    logger.warning("⚠️ 임팩트 평가 fallback (시간 역순 컷)")
    company = [a for a in articles if categories.get(a["id"]) == "company_group"]
    industry = [a for a in articles if categories.get(a["id"]) == "industry"]
    company.sort(key=lambda a: a.get("collected_at", ""), reverse=True)
    industry.sort(key=lambda a: a.get("collected_at", ""), reverse=True)

    # 톱5는 monitor 트랙 우선, 그 외 시간 역순
    monitor_first = sorted(articles, key=lambda a: (
        0 if a.get("track") == "monitor" else 1,
        a.get("collected_at", ""),
    ), reverse=False)
    top5_src = []
    for a in monitor_first[:20]:
        if a.get("track") == "monitor":
            top5_src.append(a)
        if len(top5_src) >= 5:
            break
    if len(top5_src) < 5:
        for a in articles:
            if a not in top5_src:
                top5_src.append(a)
            if len(top5_src) >= 5:
                break

    return {
        "top5_commentary": [
            {
                "article_id": a["id"],
                "marker_count": i + 1,
                "comment": (a.get("summary") or a.get("title_clean") or "")[:200],
            }
            for i, a in enumerate(top5_src[:5])
        ],
        "company_group_top10": [
            {"article_id": a["id"], "score": 50} for a in company[:10]
        ],
        "industry_top10": [
            {"article_id": a["id"], "score": 50} for a in industry[:10]
        ],
    }


def evaluate(articles: list[dict], categories: dict[int, str],
             settings: dict) -> dict:
    """LLM 호출로 임팩트 평가. 실패 시 fallback.

    Args:
        articles: 윈도우 내 기사 dict 리스트
        categories: {article_id: 'company_group' | 'industry'}
        settings: settings.json

    Returns:
        {top5_commentary, company_group_top10, industry_top10}
    """
    if not articles:
        return {"top5_commentary": [], "company_group_top10": [], "industry_top10": []}

    valid_ids = {a["id"] for a in articles if "id" in a}
    system_prompt = settings.get("daily_report_impact_prompt", DEFAULT_IMPACT_PROMPT)
    prompt = _build_prompt(articles, categories, system_prompt)

    client = get_client()
    if client is None:
        logger.warning("Gemini 미사용 — 임팩트 평가 fallback")
        return _fallback(articles, categories)

    model = settings.get("gpt_model_tone", DEFAULT_MODEL)

    # 응답 스키마 강제 — 배열이 아닌 객체로 응답하도록 못박음
    response_schema = {
        "type": "OBJECT",
        "properties": {
            "top5_commentary": {
                "type": "OBJECT",
                "properties": {
                    "rank_1": {
                        "type": "OBJECT",
                        "properties": {
                            "article_id": {"type": "INTEGER"},
                            "comment": {"type": "STRING"},
                        },
                        "required": ["article_id", "comment"],
                    },
                    "rank_2": {
                        "type": "OBJECT",
                        "properties": {
                            "article_id": {"type": "INTEGER"},
                            "comment": {"type": "STRING"},
                        },
                        "required": ["article_id", "comment"],
                    },
                    "rank_3": {
                        "type": "OBJECT",
                        "properties": {
                            "article_id": {"type": "INTEGER"},
                            "comment": {"type": "STRING"},
                        },
                        "required": ["article_id", "comment"],
                    },
                    "rank_4": {
                        "type": "OBJECT",
                        "properties": {
                            "article_id": {"type": "INTEGER"},
                            "comment": {"type": "STRING"},
                        },
                        "required": ["article_id", "comment"],
                    },
                    "rank_5": {
                        "type": "OBJECT",
                        "properties": {
                            "article_id": {"type": "INTEGER"},
                            "comment": {"type": "STRING"},
                        },
                        "required": ["article_id", "comment"],
                    },
                },
                "required": ["rank_1", "rank_2", "rank_3", "rank_4", "rank_5"],
            },
            "company_group_top10": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "article_id": {"type": "INTEGER"},
                        "score": {"type": "INTEGER"},
                    },
                    "required": ["article_id", "score"],
                },
            },
            "industry_top10": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "article_id": {"type": "INTEGER"},
                        "score": {"type": "INTEGER"},
                    },
                    "required": ["article_id", "score"],
                },
            },
        },
        "required": ["top5_commentary", "company_group_top10", "industry_top10"],
    }

    config_kwargs = {
        "max_output_tokens": MAX_OUTPUT_TOKEN,
        "temperature": 0.2,
        "response_mime_type": "application/json",
        "response_schema": response_schema,
    }
    if hasattr(types, "ThinkingConfig"):
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)

    logger.info(f"📊 임팩트 평가 시작: {len(articles)}건, model={model}")

    last_err = None
    for attempt in range(1, RETRY_MAX + 1):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(**config_kwargs),
            )
            text = resp.text or ""
            payload = _extract_json(text)
            if not payload:
                logger.error(f"❌ 임팩트 평가 JSON 파싱 실패: {text[:200]}")
                return _fallback(articles, categories)
            result = _validate(payload, valid_ids)
            n_top5 = len(result['top5_commentary'])
            n_cg = len(result['company_group_top10'])
            n_ind = len(result['industry_top10'])
            logger.info(
                f"✅ 임팩트 평가 완료: 톱5={n_top5}, 당사·그룹={n_cg}, 업계동향={n_ind}"
            )
            return result
        except Exception as e:
            last_err = e
            if _is_transient(e) and attempt < RETRY_MAX:
                logger.warning(f"⏳ 임팩트 평가 [{attempt}/{RETRY_MAX}] 일시 오류, {RETRY_DELAY}s 후 재시도: {e}")
                time.sleep(RETRY_DELAY)
                continue
            logger.error(f"❌ 임팩트 평가 실패 (attempt={attempt}): {e}")
            break

    return _fallback(articles, categories)
