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

DEFAULT_MODEL = "gemini-flash-lite-latest"
MAX_OUTPUT_TOKEN = 8192
RETRY_MAX = 3
RETRY_DELAY = 2

DEFAULT_IMPACT_PROMPT = """당신은 SK하이닉스 곽노정 CEO입니다. 오늘 아침 비서가 기사 스크랩 수백 건을 책상 위에 올렸고, 당신은 그 중 가장 먼저 읽을 기사 3~5건을 직접 골라야 합니다.

[언어 규칙 — 최우선]
모든 출력은 반드시 한국어로 작성합니다. 영어 표기는 고유명사(SK하이닉스, HBM, AI, ETF, TSMC 등)와 숫자·단위에만 허용합니다. comment 안의 영어 문장 사용은 금지합니다.

[CEO에게 진짜 중요한 기사란]
1. 자사(SK하이닉스)·CEO 본인(곽노정)이 주인공인 기사 — 실적, 인사, 투자, 사고
2. 그룹 회장(최태원)·계열사의 의사결정이 자사에 영향 주는 기사
3. 자사에 즉시 대응을 요구하는 외부 사건 — 정책·규제·고객사 발표·경쟁사 액션
4. 시장이 자사를 어떻게 평가하는지 — 단, 단순 시황·증시 종합은 제외

[배경 정보로 제공되는 시그널]
각 기사에는 시스템이 미리 계산한 pre_score(0~100) 가 붙어 있습니다. 이 점수는 CEO 관점 가중치(자사 주체성 50, 외부 임팩트 25, 매체 신호 15, 톤 시그널 10)를 합산한 참고지표입니다. 절대값이 아니므로 본인 판단을 우선시하되, 60점 이상이면 진지하게 후보로 검토, 30점 미만이면 거의 노이즈로 간주하세요.

추가로 각 기사에는 다음 시그널이 함께 제공됩니다:
- track: monitor(자사 직접 후보) / reference(업계·참고)
- tone: 비우호/양호/일반/미분석 + confidence
- tone_reason: 톤 분류 LLM이 적은 사유 (비우호일 때 PR 위기 단서)
- tone_sentences: 비우호 문장 원문 (commentary 작성 시 인용 가능)
- 매칭키워드: 어느 검색 키워드로 잡혔는지

[작업 1] top5_commentary — rank_1 ~ rank_5
- 진짜 중요한 기사만 선정. 3건이면 3건, 4건이면 4건, 최대 5건.
- 빈자리 채우려고 시황·노이즈 기사를 끌어 올리지 마시오. **빈자리는 그대로 두는 게 맞습니다.**
- rank_1은 자사 직접(SK하이닉스·곽노정 등) 기사 중 pre_score 최상위. 그런 기사가 없을 때만 그룹·외부 사건이 rank_1이 될 수 있습니다.
- comment는 2~4문장, "CEO에게 보고하는 톤"으로 작성. 예: "...로 분석됩니다", "...에 대한 대응이 필요합니다"
- 비우호 기사라면 tone_reason과 tone_sentences를 활용해 구체적 사유를 comment에 녹일 것
- 5건 미만으로 선정하는 경우, 사용하지 않는 rank 키는 응답에서 생략하시오 (rank_1만, 또는 rank_1~3만 등)

[작업 2] company_group_top10 — 당사·그룹 관련 톱10
- track=monitor 또는 제목에 SK 그룹 키워드(SK하이닉스, 최태원, SK그룹 등)가 등장하는 기사 중 임팩트 상위 10건
- 같은 사건 중복 보도 시 메이저 언론사 1건만 선정
- score는 pre_score를 기준선으로 삼되 본인 판단으로 ±15 조정 가능

[작업 3] industry_top10 — 업계동향 톱10
- track=reference이면서 제목에 SK 그룹 키워드 없는 기사 중 임팩트 상위 10건
- 단순 시황(S&P500/코스피/지수) 단독 기사는 제외
- 정책·규제·경쟁사 액션·고객사 발표 등 자사에 시사점 있는 업계 동향 우선
- score는 pre_score를 기준선으로 삼되 본인 판단으로 ±15 조정 가능

[중복 방지] 같은 article_id를 company_group_top10과 industry_top10 양쪽에 넣지 마시오.

[출력 형식] 아래 구조의 단일 JSON으로만 응답:
{
  "top5_commentary": {
    "rank_1": {"article_id": <int>, "comment": "<2-4문장>"},
    "rank_2": {"article_id": <int>, "comment": "<2-4문장>"},
    "rank_3": {"article_id": <int>, "comment": "<2-4문장>"}
    // rank_4, rank_5는 진짜 중요한 기사가 있을 때만
  },
  "company_group_top10": [{"article_id": <int>, "score": <0-100>}],
  "industry_top10": [{"article_id": <int>, "score": <0-100>}]
}

article_id는 반드시 입력에 등장한 ID만 사용하시오.
"""


def _is_transient(err: Exception) -> bool:
    s = str(err).lower()
    return any(k in s for k in ("503", "unavailable", "429", "resource_exhausted",
                                 "deadline_exceeded", "timeout"))


def _build_prompt(articles: list[dict], categories: dict[int, str], system_prompt: str) -> str:
    """STEP-IMPACT-2: 모든 시그널 + pre_score 포함."""
    lines = [system_prompt, "", "[기사 목록]"]
    # 사전 점수 정렬 (LLM이 상위부터 보도록)
    scored = []
    for a in articles:
        ps, bd = _prescore(a)
        scored.append((ps, bd, a))
    scored.sort(key=lambda x: -x[0])

    # commentary 후보 상위 20건만 tone_sentences 전체 포함 (토큰 절약)
    TOP_FOR_DETAIL = 20

    for idx, (ps, bd, a) in enumerate(scored):
        aid = a.get("id")
        cat = categories.get(aid, "industry")
        track = a.get("track") or ""
        press = (a.get("press") or "").replace("|", "/")
        title = (a.get("title_clean") or a.get("title") or "").replace("|", "/")[:140]
        summary = (a.get("summary") or "").replace("|", "/").replace("\n", " ")[:250]
        tc = a.get("tone_classification") or "-"
        conf = a.get("tone_confidence") or "-"
        hostile = a.get("tone_hostile") or 0
        total = a.get("tone_total") or 0
        reason = (a.get("tone_reason") or "").replace("|", "/").replace("\n", " ")[:200]
        mkw = (a.get("matched_kw") or "").replace("|", "/")[:80]

        lines.append("")
        lines.append(f"[ID={aid}] pre_score={ps} (자사{bd['subject']}+외부{bd['external']}+매체{bd['press']}+톤{bd['tone']}) | category={cat} | track={track}")
        lines.append(f"  매체: {press} | 매칭키워드: {mkw}")
        lines.append(f"  제목: {title}")
        if summary:
            lines.append(f"  요약: {summary}")
        if tc and tc != "-":
            lines.append(f"  톤: {tc} (confidence={conf}, hostile={hostile}/{total})")
        if reason:
            lines.append(f"  톤 사유: {reason}")

        # 상위 20건만 비우호 문장 원문 포함
        if idx < TOP_FOR_DETAIL and tc == "비우호":
            try:
                sents_raw = a.get("tone_sentences")
                if sents_raw:
                    sents = json.loads(sents_raw) if isinstance(sents_raw, str) else sents_raw
                    if isinstance(sents, list) and sents:
                        joined = " / ".join(s.replace("|", "/").replace("\n", " ")[:120] for s in sents[:5])
                        lines.append(f"  비우호 문장: {joined}")
            except Exception:
                pass
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



# ──────────────────────────────────────────────────────────────
#  STEP-IMPACT-2: CEO 관점 결정론적 사전 점수
# ──────────────────────────────────────────────────────────────
SK_HYNIX_DIRECT = ("SK하이닉스", "하이닉스", "SKhynix", "hynix", "솔리다임", "곽노정")
SK_GROUP_EXTRA  = ("SK그룹", "SK스퀘어", "SK이노베이션", "SK텔레콤", "SKT", "SK온",
                   "SK가스", "SK디스커버리", "SK바이오팜", "SK바이오사이언스",
                   "SK네트웍스", "SK실트론", "SK시그넷", "SK(주)", "SK주식회사",
                   "최태원", "최창원", "최재원")

POLICY_KEYWORDS = ("수출규제", "수출 규제", "반도체법", "반도체 법", "상무부", "관세",
                   "중국 제재", "미국 제재", "백악관", "EU 집행위", "공정위", "공정거래위",
                   "전력기기", "데이터센터", "전력망")
RIVAL_KEYWORDS  = ("엔비디아", "NVIDIA", "삼성전자", "TSMC", "마이크론", "Micron",
                   "AMD", "인텔", "Intel")
MARKET_NOISE_KEYWORDS = ("S&P500", "S&P 500", "코스피", "코스닥", "환율", "달러/원",
                         "나스닥", "다우", "지수", "증시", "랠리", "마감", "7400선", "7000선")
EXCLUSIVE_PATTERNS = ("[단독]", "<단독>", "[독점]", "[특종]")
SPEED_PATTERNS    = ("[속보]", "<속보>")

MAJOR_PRESS_NAMES = ("조선일보", "중앙일보", "동아일보", "한국경제", "매일경제",
                     "한겨레", "경향신문", "서울경제", "파이낸셜뉴스", "헤럴드경제",
                     "아시아경제", "문화일보", "이데일리", "머니투데이")
WIRE_PRESS_NAMES  = ("연합뉴스", "뉴시스", "뉴스1", "YNA", "Yonhap")


def _has_any(text: str, kws) -> bool:
    if not text:
        return False
    tl = text.lower()
    return any(k.lower() in tl for k in kws)


def _count_in(text: str, kws) -> int:
    if not text:
        return 0
    tl = text.lower()
    return sum(tl.count(k.lower()) for k in kws)


def _prescore(a: dict) -> tuple[int, dict]:
    """CEO 관점 결정론적 점수. (총점, breakdown) 반환."""
    title = (a.get("title_clean") or a.get("title") or "").strip()
    summary = a.get("summary") or ""
    press = a.get("press") or ""

    bd = {"subject": 0, "external": 0, "press": 0, "tone": 0}

    # 1) SK 주체성 0~50
    if _has_any(title, SK_HYNIX_DIRECT):
        bd["subject"] = 50
    elif _has_any(title, SK_GROUP_EXTRA):
        bd["subject"] = 35
    else:
        body_hits = _count_in(summary, SK_HYNIX_DIRECT)
        if body_hits >= 2:
            bd["subject"] = 15
        elif body_hits == 1:
            bd["subject"] = 5
        else:
            bd["subject"] = 0

    # 2) 외부 임팩트 0~25
    is_market_noise = _has_any(title, MARKET_NOISE_KEYWORDS) and not _has_any(title, SK_HYNIX_DIRECT)
    if is_market_noise:
        bd["external"] = 0
    elif _has_any(title, POLICY_KEYWORDS) and bd["subject"] >= 15:
        bd["external"] = 25
    elif _has_any(title, RIVAL_KEYWORDS) and _has_any(title, SK_HYNIX_DIRECT):
        bd["external"] = 20
    elif _has_any(title, POLICY_KEYWORDS):
        bd["external"] = 5
    elif _has_any(title, RIVAL_KEYWORDS):
        bd["external"] = 3
    else:
        bd["external"] = 0

    # 3) 매체·보도 신호 0~15
    p = 0
    is_major = any(m in press for m in MAJOR_PRESS_NAMES)
    is_wire  = any(m in press for m in WIRE_PRESS_NAMES)
    if is_major and bd["subject"] >= 35:
        p = 15
    elif is_major:
        p = 8
    elif is_wire and bd["subject"] < 35:
        p = max(0, p - 5)  # 통신사 단순 시황 감점
    if any(x in title for x in EXCLUSIVE_PATTERNS):
        p += 5
    elif any(x in title for x in SPEED_PATTERNS):
        p += 3
    bd["press"] = max(0, min(p, 15))

    # 4) 톤 시그널 0~10 — 주체성과 곱해야 의미
    tc = a.get("tone_classification") or ""
    conf = (a.get("tone_confidence") or "").lower()
    if tc == "비우호":
        if bd["subject"] >= 35:
            bd["tone"] = 10 if conf in ("high", "상", "높음") else 7
        else:
            bd["tone"] = 2  # 노이즈성 비우호
    elif tc == "양호" and bd["subject"] >= 35:
        bd["tone"] = 7
    else:
        bd["tone"] = 0

    total = max(0, bd["subject"] + bd["external"] + bd["press"] + bd["tone"])
    return total, bd


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



# ===== STEP-IMPACT-3: 2-stage LLM =====
STAGE1_PROMPT = """당신은 SK하이닉스 PR 분석가입니다. 아래 기사 목록을 보고 각 기사가 CEO에게 보고할 만큼 중요한지 0~100점으로 평가합니다.

[점수 기준]
- 상: SK하이닉스/곽노정/솔리다임이 제목의 주체. 즉각 보고 필수.SK그룹/최태원/계열사가 주체이거나, SK하이닉스에 직접 영향(고객사·경쟁사·정책·규제).
- 중: 반도체 산업·메모리·HBM·AI칩 등 SK하이닉스 사업에 간접 영향.일반 산업·경제 동향 중 참고할 만한 것.
- 하: 시황 헤드라인, 무관한 기사, 단순 종목 나열.

[출력]
JSON 배열만 출력. 사유·설명·코드블록 금지.
[{"id": 123, "s": 85}, {"id": 124, "s": 12}, ...]
모든 입력 id에 대해 점수 부여 (누락 금지).
"""


def _stage1_filter(articles: list[dict], categories: dict[int, str]) -> dict[int, int]:
    """Stage 1: 전체 기사에 0~100 점수 부여. 배치 분할로 JSON truncate 방지."""
    if not articles:
        return {}
    try:
        from google import genai
        from google.genai import types as gtypes
    except ImportError:
        logger.error("[Stage1] google-genai 미설치")
        return {a["id"]: 50 for a in articles}

    import os, json as _json
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.warning("[Stage1] GEMINI_API_KEY 없음 - 전체 50점 fallback")
        return {a["id"]: 50 for a in articles}

    # Flash Lite 최대 출력 토큰 8192 → 1건당 ~12 토큰 → 안전하게 500건/배치
    BATCH_SIZE = 500
    client = genai.Client(api_key=api_key)
    all_scores: dict[int, int] = {}

    batches = [articles[i:i+BATCH_SIZE] for i in range(0, len(articles), BATCH_SIZE)]
    logger.info(f"[Stage1] {len(articles)}건 → {len(batches)}배치 ({BATCH_SIZE}건씩)")

    for bi, batch in enumerate(batches, 1):
        lines = []
        for a in batch:
            aid = a.get("id")
            cat = categories.get(aid, "industry")
            title = (a.get("title_clean") or a.get("title") or "")[:80]
            summary = (a.get("summary") or a.get("description") or "")[:100]
            tone = a.get("tone_classification") or "-"
            press = (a.get("press") or "-")[:20]
            track = a.get("track") or "-"
            lines.append(f"{aid}|{cat}|{track}|{tone}|{press}|{title} :: {summary}")
        body = "\n".join(lines)
        full_prompt = STAGE1_PROMPT + "\n[기사 목록]\n" + body

        try:
            resp = client.models.generate_content(
                model="gemini-flash-lite-latest",
                contents=full_prompt,
                config=gtypes.GenerateContentConfig(
                    temperature=0,
                    max_output_tokens=8192,
                    response_mime_type="application/json",
                ),
            )
            text = (resp.text or "").strip()
            if text.startswith("```"):
                text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
                text = re.sub(r"\n?```$", "", text)

            # 강건한 파싱: 완전한 JSON 실패 시 정규식으로 항목 추출
            parsed = []
            try:
                parsed = _json.loads(text)
            except _json.JSONDecodeError:
                # truncate된 경우 마지막 완전한 객체까지만 파싱
                matches = re.findall(r'\{\s*"id"\s*:\s*(\d+)\s*,\s*"s"\s*:\s*(\d+)\s*\}', text)
                parsed = [{"id": int(m[0]), "s": int(m[1])} for m in matches]
                logger.warning(f"[Stage1] 배치 {bi} JSON 손상 → 정규식 복구 {len(parsed)}건")

            cnt = 0
            for item in parsed:
                try:
                    aid = int(item.get("id"))
                    s = int(item.get("s", 0))
                    all_scores[aid] = max(0, min(100, s))
                    cnt += 1
                except (TypeError, ValueError):
                    continue
            logger.info(f"[Stage1] 배치 {bi}/{len(batches)}: 입력 {len(batch)}건 → 파싱 {cnt}건")
        except Exception as e:
            logger.error(f"[Stage1] 배치 {bi} 실패: {e}")

    # 누락된 기사는 0점 (Stage2에서 자동 탈락)
    for a in articles:
        all_scores.setdefault(a["id"], 0)
    logger.info(f"[Stage1] 최종 점수 부여: {len(all_scores)}건")
    return all_scores


def _select_top_by_track(articles: list[dict], scores: dict[int, int],
                          per_track: int = 100) -> list[dict]:
    """Stage1 점수 기준으로 track별 상위 N건 추출 (점수 DESC, 최신 DESC)."""
    monitor = [a for a in articles if (a.get("track") or "") == "monitor"]
    reference = [a for a in articles if (a.get("track") or "") != "monitor"]

    def _sort_key(a):
        return (-scores.get(a["id"], 0), -(a.get("collected_at") or "").__hash__())

    # 안전한 정렬: 점수 DESC, collected_at DESC
    def _key(a):
        s = scores.get(a["id"], 0)
        ts = a.get("collected_at") or a.get("pub_date") or ""
        return (-s, ts)  # 점수 내림차순, ts는 문자열 → 오름차순이지만 동점일 때만 의미
    monitor.sort(key=lambda a: (-scores.get(a["id"], 0), a.get("collected_at") or ""), reverse=False)
    monitor.sort(key=lambda a: scores.get(a["id"], 0), reverse=True)
    reference.sort(key=lambda a: scores.get(a["id"], 0), reverse=True)

    top_mon = monitor[:per_track]
    top_ref = reference[:per_track]
    logger.info(f"[Stage1] track별 추출: monitor={len(top_mon)} reference={len(top_ref)}")
    return top_mon + top_ref
# ===== END STEP-IMPACT-3 =====


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
    # STEP-IMPACT-3: Stage 1 필터 (전체 → track별 TOP 100)
    if len(articles) > 200:
        logger.info(f"[Stage1] 전체 {len(articles)}건 → 필터링 시작")
        _scores = _stage1_filter(articles, categories)
        articles = _select_top_by_track(articles, _scores, per_track=100)
        logger.info(f"[Stage1] 필터 결과 {len(articles)}건 → Stage2 진행")
    # ===== Stage 2 (기존 로직) =====
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
                "required": ["rank_1"],  # STEP-IMPACT-2: 3~5건 가변, rank_1만 필수
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
