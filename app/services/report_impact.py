# app/services/report_impact.py
"""
일간 리포트 임팩트 평가 모듈.

목표:
- 기존 report_builder.py가 기대하는 출력 스키마는 유지한다.
- 내부 판단은 '기사 단건 랭킹'이 아니라 '내신 보고용 이슈 선별'에 가깝게 만든다.

반환 스키마:
{
  "top5_commentary": [
    {"article_id": int, "marker_count": 1~5, "comment": str}
  ],
  "company_group_top10": [{"article_id": int, "score": 0~100}],
  "industry_top10": [{"article_id": int, "score": 0~100}]
}

주의:
- article_id는 여전히 대표 기사 1건을 뜻한다. 같은 이슈의 중복 기사는 내부적으로 제거한다.
- LLM 실패 시에도 규칙 기반 점수/중복 제거로 보고서 품질을 최대한 유지한다.
"""

from __future__ import annotations

import hashlib
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

# ──────────────────────────────────────────────────────────────
#  프롬프트: 특정 이슈 카테고리 하드코딩보다 '판단 패턴'을 일반화
# ──────────────────────────────────────────────────────────────
DEFAULT_IMPACT_PROMPT = """당신은 SK하이닉스 홍보/대외협력 조직의 데일리 뉴스 브리핑 에디터입니다.
목표는 기사 랭킹이 아니라, 경영진에게 보고할 '주요 이슈'를 선별해 내신 리포트 문체로 정리하는 것입니다.

[언어 규칙 — 최우선]
모든 출력은 반드시 한국어로 작성합니다. 영어 표기는 고유명사(SK하이닉스, HBM, AI, ETF, TSMC 등)와 숫자·단위에만 허용합니다.

[핵심 원칙]
1. TOP 5는 '중요 기사 5개'가 아니라 '오늘 보고할 주요 이슈 최대 5개'입니다.
2. 같은 사건의 여러 기사는 하나의 이슈로 묶고, 대표 기사 1건만 article_id로 고릅니다.
3. 빈칸을 채우기 위해 단순 시황, 목표가 반복, 제목만 다른 중복 기사를 넣지 않습니다.
4. 사람 보고서처럼 '무슨 일이 있었는지 + 언론/시장/정책권이 어떻게 해석했는지 + 당사에 왜 중요한지'를 씁니다.
5. 자사 직접 이슈만 고르지 말고, 경영진이 알아야 할 외부 변수도 포함합니다.

[보고 가치가 큰 이슈의 판단 패턴]
- 자사/그룹: SK하이닉스, 곽노정, 최태원, SK그룹/계열사, 투자, 실적, 생산, 공시, 재무, 법무, 평판, 인재, 안전, ESG, 협회/대외활동
- 고객/파트너/공급망: MS, 오픈AI, 엔비디아, AMD, 인텔, 구글, 아마존, 메타, 애플, 테슬라, 샌디스크, 키옥시아 등 주요 고객·파트너의 전략 변화
- 기술/제품: HBM, HBF, D램, 낸드, SSD, CXL, PIM, 패키징, 하이브리드 본딩, 데이터센터, 전력, 냉각, AI 에이전트, 메모리 수요·대체기술
- 경쟁사/업계: 삼성전자, 마이크론, TSMC, 라피더스, 소프트뱅크 등 경쟁사·대체재·산업질서 변화
- 정책/규제/정치권: 반도체 지원, 보조금, 관세, 수출규제, 대중 제재, 전력망, 데이터센터 규제, 노동정책, 국민배당·초과이익 배분 논쟁
- 평판/여론/PR: 보도자료 확산, 기획 Comm, 다큐/르포/인터뷰, 사설·칼럼의 논조 변화, 노조·성과급·사회적 환원 논쟁
- 매크로/지정학: 중동·호르무즈·전쟁·유가·환율·미중갈등 등 반도체 공급망이나 고객 투자심리에 연결되는 사안

[우선순위]
1순위: 당사 직접 사안 중 경영 판단, 대응, 메시지 관리가 필요한 이슈
2순위: 당사 평판·PR 성과·보도 확산 이슈
3순위: 정책·규제·노동·사회적 논쟁처럼 당사에 대응 필요성이 있는 외부 이슈
4순위: 고객사/파트너/경쟁사의 전략 변화와 기술 로드맵 변화
5순위: 시장평가·수급·목표주가·시황. 단, 단순 반복이면 낮게 둡니다.

[중복 묶음 규칙]
다음은 반드시 하나의 이슈로 묶습니다.
- 같은 행사/인터뷰/르포/다큐/보도자료 확산
- 같은 증권사 리포트 또는 목표주가 상향·하향 반복
- 같은 정책 발언과 그에 따른 시장 반응
- 같은 노조·성과급·파업 논쟁의 후속/칼럼/연결 기사
- 같은 공급계약, 투자, 공시, 채용, 법원/소송 이슈
- 같은 시황을 제목만 바꿔 쓴 기사

[제외 또는 강등]
- 코스피/코스닥/나스닥/환율/시총 순위 등 단순 시황
- 자사와 연결되지 않는 일반 정치·사건·생활 기사
- 제목에 SK하이닉스가 들어가지만 실질은 주가/목표가 반복인 기사
- 이미 더 중요한 대표 기사가 있는 중복 기사
단, 정책·규제·공급망·외국인 대규모 매도·사회적 논쟁과 연결되면 포함할 수 있습니다.

[comment 문체]
- 1~3문장으로 작성합니다.
- '긍정적 기사임', '부정적 맥락', '투자심리 위축' 같은 분류 설명문은 금지합니다.
- 예시 문체:
  - "당사가 ...했습니다. 언론은 ...로 해석했습니다."
  - "... 관련 보도가 다수 이어지고 있습니다. 주요 매체는 ...를 부각했습니다."
  - "... 발언 이후 시장에서는 ... 반응이 나타났습니다. 당사와 메모리 업계에 대한 ... 논의로 확산될 수 있습니다."
  - "삼성전자가 ... 중입니다. 업계에서는 ... 가능성을 주목하고 있습니다."

[작업 1] top5_commentary
- 최대 5개 이슈만 선정합니다. 진짜 중요하지 않으면 3~4개만 뽑아도 됩니다.
- 각 rank에는 해당 이슈를 대표하는 article_id와 보고문체 comment를 넣습니다.

[작업 2] company_group_top10
- track=monitor 또는 제목/요약에 SK하이닉스·SK그룹·계열사·최태원·곽노정 등 당사/그룹 관련성이 있는 이슈를 고릅니다.
- 같은 이슈의 중복 보도는 대표 기사 1건만 넣습니다.

[작업 3] industry_top10
- 당사/그룹 직접 이슈가 아닌 업계·정책·경쟁사·고객사·기술·매크로 이슈를 고릅니다.
- 단순 시황은 제외하고, 경영진이 알아야 할 시사점이 있는 이슈를 우선합니다.

[출력 형식]
반드시 아래 구조의 단일 JSON 객체만 응답합니다. 설명, 마크다운, 코드블록은 금지합니다.
{
  "top5_commentary": {
    "rank_1": {"article_id": 123, "comment": "..."},
    "rank_2": {"article_id": 456, "comment": "..."}
  },
  "company_group_top10": [{"article_id": 123, "score": 90}],
  "industry_top10": [{"article_id": 789, "score": 85}]
}
article_id는 반드시 입력에 등장한 ID만 사용합니다.
"""


# ──────────────────────────────────────────────────────────────
#  키워드/판단 재료
# ──────────────────────────────────────────────────────────────
SK_HYNIX_DIRECT = (
    "SK하이닉스", "하이닉스", "SK hynix", "SKhynix", "hynix", "솔리다임", "곽노정"
)
SK_GROUP_EXTRA = (
    "SK그룹", "SK스퀘어", "SK이노베이션", "SK텔레콤", "SKT", "SK온", "SKC", "SK가스",
    "SK디스커버리", "SK바이오팜", "SK바이오사이언스", "SK네트웍스", "SK실트론",
    "SK시그넷", "SK(주)", "SK주식회사", "최태원", "최창원", "최재원"
)
RIVAL_KEYWORDS = (
    "삼성전자", "삼성", "TSMC", "마이크론", "Micron", "인텔", "Intel", "라피더스",
    "Rapidus", "소프트뱅크", "SoftBank", "사이메모리"
)
CUSTOMER_PARTNER_KEYWORDS = (
    "엔비디아", "NVIDIA", "MS", "마이크로소프트", "Microsoft", "오픈AI", "OpenAI",
    "구글", "Google", "아마존", "Amazon", "AWS", "메타", "Meta", "애플", "Apple",
    "AMD", "테슬라", "Tesla", "샌디스크", "SanDisk", "키옥시아", "Kioxia", "앤트로픽", "Anthropic"
)
TECH_KEYWORDS = (
    "HBM", "HBF", "D램", "DRAM", "낸드", "NAND", "SSD", "CXL", "PIM", "HBM4", "HBM4E",
    "패키징", "하이브리드 본딩", "본딩", "TSV", "웨이퍼", "팹", "파운드리", "AI칩",
    "가속기", "데이터센터", "전력", "냉각", "메모리", "AI 에이전트", "에이전틱", "AGI"
)
POLICY_REG_KEYWORDS = (
    "정부", "청와대", "백악관", "국회", "민주당", "국민의힘", "금융위", "산업부", "상무부",
    "USTR", "관세", "수출규제", "수출 규제", "제재", "보조금", "반도체법", "반도체 법",
    "국민성장펀드", "국민배당", "초과이익", "전력망", "데이터센터 규제", "노동부", "법원"
)
LABOR_REPUTATION_KEYWORDS = (
    "노조", "파업", "임단협", "임금협상", "성과급", "보상", "상생", "안전보건", "윤리", "ESG",
    "다큐", "르포", "인터뷰", "칼럼", "사설", "논란", "비판", "여론", "커뮤니케이션", "Comm", "보도자료"
)
MARKET_KEYWORDS = (
    "목표주가", "투자의견", "증권", "외국인", "순매도", "순매수", "주가", "시총", "자사주",
    "ADR", "소각", "배당", "환율", "코스피", "코스닥", "나스닥", "S&P500", "다우", "증시", "특징주"
)
MACRO_GEO_KEYWORDS = (
    "이란", "호르무즈", "중동", "전쟁", "종전", "유가", "원유", "대만", "중국", "미중", "파키스탄",
    "총격", "암살", "안보", "동맹"
)
LOW_VALUE_MARKET_ONLY = (
    "개장", "마감", "상승 출발", "하락 출발", "장중", "사상 최고", "돌파", "랠리", "강세", "약세"
)
EXCLUSIVE_PATTERNS = ("[단독]", "<단독>", "단독", "[독점]", "[특종]")
SPEED_PATTERNS = ("[속보]", "<속보>", "속보")
FOLLOWUP_PATTERNS = ("연결", "종합", "종합2보", "종합3보", "가판", "조간", "칼럼", "사설")

MAJOR_PRESS_NAMES = (
    "조선일보", "조선", "중앙일보", "중앙", "동아일보", "동아", "한국경제", "한경", "매일경제", "매경",
    "한겨레", "경향신문", "경향", "서울경제", "서경", "파이낸셜뉴스", "파뉴", "헤럴드경제",
    "아시아경제", "문화일보", "문화", "이데일리", "머니투데이", "머투", "전자신문", "전자",
    "조선비즈", "조비", "블로터", "디일렉", "더벨", "연합인포맥스", "연합인포"
)
WIRE_PRESS_NAMES = ("연합뉴스", "연합", "뉴시스", "뉴스1", "YNA", "Yonhap")

STOPWORDS = {
    "단독", "속보", "종합", "조간", "가판", "오늘", "내일", "어제", "관련", "기자", "칼럼", "사설",
    "억원", "조원", "만원", "달러", "종합2보", "종합3보", "특징주", "AI픽"
}


def _safe_text(*parts: object) -> str:
    return " ".join(str(p or "") for p in parts).strip()


def _norm(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[\[\]<>〈〉()（）{}'\"“”‘’…·•,.:;!?~|/\\]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _has_any(text: str, kws) -> bool:
    if not text:
        return False
    tl = text.lower()
    return any(str(k).lower() in tl for k in kws)


def _count_in(text: str, kws) -> int:
    if not text:
        return 0
    tl = text.lower()
    return sum(tl.count(str(k).lower()) for k in kws)


def _article_text(a: dict, include_summary: bool = True) -> str:
    title = a.get("title_clean") or a.get("title") or ""
    summary = a.get("summary") or a.get("description") or ""
    matched = a.get("matched_kw") or ""
    press = a.get("press") or ""
    return _safe_text(title, summary if include_summary else "", matched, press)


def _is_company_related(a: dict, categories: dict[int, str] | None = None) -> bool:
    aid = a.get("id")
    if categories and categories.get(aid) == "company_group":
        return True
    text = _article_text(a)
    return (a.get("track") == "monitor") or _has_any(text, SK_HYNIX_DIRECT) or _has_any(text, SK_GROUP_EXTRA)


def _is_market_noise(a: dict) -> bool:
    title = _safe_text(a.get("title_clean") or a.get("title"))
    body = _article_text(a)
    market = _has_any(title, MARKET_KEYWORDS)
    low = _has_any(title, LOW_VALUE_MARKET_ONLY) or _has_any(title, ("코스피", "코스닥", "나스닥", "S&P500", "다우", "환율", "시총"))
    has_substance = _has_any(body, SK_HYNIX_DIRECT + SK_GROUP_EXTRA + POLICY_REG_KEYWORDS + LABOR_REPUTATION_KEYWORDS + TECH_KEYWORDS + CUSTOMER_PARTNER_KEYWORDS + MACRO_GEO_KEYWORDS)
    # 제목이 순수 지수/시황이고 실질 연결고리가 없으면 노이즈
    return bool(market and low and not has_substance)


def _issue_family(a: dict) -> str:
    """하드코딩된 좁은 분류가 아니라, 중복 제거용 넓은 이슈 패밀리."""
    text = _article_text(a)
    title = _safe_text(a.get("title_clean") or a.get("title"))
    if _has_any(text, ("목표주가", "투자의견", "리포트", "증권", "주가 더 간다", "간다")) and _has_any(text, SK_HYNIX_DIRECT + ("삼전", "삼성전자")):
        return "market_rating"
    if _has_any(text, ("성과급", "보상", "노조", "파업", "임단협", "임금협상")):
        return "labor_compensation"
    if _has_any(text, ("국민배당", "초과이익", "윈드폴", "사회적 환원", "배당이냐 월급")):
        return "profit_distribution"
    if _has_any(text, ("다큐", "방진복", "이름 없는 영웅", "30년 열정", "르포", "청년하이파이브", "보도자료", "윤리적인 기업", "안전보건")):
        return "reputation_pr"
    if _has_any(text, ("CEO 서밋", "빌 게이츠", "나델라", "MS CEO", "마이크로소프트")):
        return "customer_ms"
    if _has_any(text, ("M15X", "용인", "클러스터", "팹", "공장", "생산거점", "평택", "테일러")):
        return "fab_investment"
    if _has_any(text, ("HBM", "HBF", "HB3DM", "하이브리드 본딩", "PIM", "CXL", "메모리 컨트롤러", "D램", "낸드")):
        return "memory_technology"
    if _has_any(text, ("오픈AI", "앤트로픽", "구글", "아마존", "메타", "엔비디아", "인텔", "테슬라", "AI 에이전트", "AGI")):
        return "ai_customer_ecosystem"
    if _has_any(text, ("관세", "수출규제", "보조금", "상무부", "USTR", "국민성장펀드", "정책", "정부", "백악관", "국회", "전력망")):
        return "policy_regulation"
    if _has_any(text, ("이란", "호르무즈", "중동", "전쟁", "종전", "원유", "유가")):
        return "geopolitics_supplychain"
    if _has_any(title, MARKET_KEYWORDS):
        return "market_general"
    return "general"


def _salient_tokens(text: str, max_tokens: int = 5) -> list[str]:
    n = _norm(text)
    tokens = re.findall(r"[a-zA-Z0-9]+|[가-힣]{2,}", n)
    kept: list[str] = []
    for t in tokens:
        if t in STOPWORDS:
            continue
        if len(t) <= 1:
            continue
        # 너무 일반적인 기사 동사는 제거
        if t in {"한다", "했다", "된다", "전망", "가능성", "업계", "기업", "시장", "기술", "사업", "규모", "기반", "추진"}:
            continue
        kept.append(t)
    # 원래 순서를 유지한 unique
    out: list[str] = []
    for t in kept:
        if t not in out:
            out.append(t)
        if len(out) >= max_tokens:
            break
    return out


def _issue_key(a: dict) -> str:
    """같은 이슈 반복 방지를 위한 key. 넓은 family + 핵심 토큰 fingerprint."""
    title = _safe_text(a.get("title_clean") or a.get("title"))
    text = _article_text(a)
    family = _issue_family(a)

    # 패밀리별로 핵심 엔티티가 강하면 같은 이슈로 묶는다.
    strong_phrases = [
        "국민배당", "초과이익", "성과급", "삼성전자 노조", "MS CEO", "빌 게이츠", "나델라",
        "원티드 하이파이브", "다큐3일", "IEEE", "용인", "M15X", "ADR", "Ethisphere", "HBF",
        "키옥시아", "샌디스크", "HB3DM", "호르무즈", "테일러", "평택5공장", "국민성장펀드"
    ]
    for p in strong_phrases:
        if p.lower() in text.lower():
            return f"{family}:{p.lower()}"

    tokens = _salient_tokens(title, 5)
    if len(tokens) < 3:
        tokens = _salient_tokens(text, 5)
    sig = "_".join(tokens[:5]) if tokens else hashlib.md5(_norm(title).encode()).hexdigest()[:8]
    return f"{family}:{sig}"


def _press_score(press: str, title: str, subject: int) -> int:
    p = 0
    is_major = any(m in (press or "") for m in MAJOR_PRESS_NAMES)
    is_wire = any(m in (press or "") for m in WIRE_PRESS_NAMES)
    if is_major and subject >= 30:
        p += 12
    elif is_major:
        p += 8
    elif is_wire:
        p += 4
    if any(x in title for x in EXCLUSIVE_PATTERNS):
        p += 6
    elif any(x in title for x in SPEED_PATTERNS):
        p += 2
    return max(0, min(p, 15))


def _prescore(a: dict) -> tuple[int, dict]:
    """내신 보고 관점의 규칙 기반 점수. LLM에 기준선으로 제공하고 fallback에도 사용."""
    title = _safe_text(a.get("title_clean") or a.get("title"))
    summary = _safe_text(a.get("summary") or a.get("description"))
    press = _safe_text(a.get("press"))
    text = _safe_text(title, summary, a.get("matched_kw"))

    bd = {
        "subject": 0,       # 당사/그룹 직접성
        "strategy": 0,      # 사업·기술·고객·투자 중요도
        "risk": 0,          # 정책·규제·노동·평판·지정학 리스크
        "press": 0,         # 매체/단독/확산 신호
        "tone": 0,          # 비우호/양호 톤 신호
        "penalty": 0,       # 단순 시황/중복성 감점
    }

    # 1) 당사/그룹 직접성 0~30
    if _has_any(title, SK_HYNIX_DIRECT):
        bd["subject"] = 30
    elif _has_any(text, SK_HYNIX_DIRECT):
        bd["subject"] = 24
    elif _has_any(title, SK_GROUP_EXTRA):
        bd["subject"] = 22
    elif _has_any(text, SK_GROUP_EXTRA):
        bd["subject"] = 16
    elif a.get("track") == "monitor":
        bd["subject"] = 14

    # 2) 전략/사업/기술/고객 0~25
    strategic_hits = 0
    strategic_hits += 2 if _has_any(text, TECH_KEYWORDS) else 0
    strategic_hits += 2 if _has_any(text, CUSTOMER_PARTNER_KEYWORDS) else 0
    strategic_hits += 2 if _has_any(text, RIVAL_KEYWORDS) else 0
    strategic_hits += 2 if _has_any(text, ("투자", "생산", "공장", "팹", "클러스터", "공급", "계약", "표준화", "수상", "선정", "상장", "소각", "자사주")) else 0
    strategic_hits += 1 if _has_any(text, ("AI", "에이전트", "데이터센터", "전력", "메모리")) else 0
    bd["strategy"] = min(25, strategic_hits * 4)
    if bd["subject"] >= 20 and bd["strategy"] >= 12:
        bd["strategy"] = min(25, bd["strategy"] + 5)

    # 3) 리스크/정책/평판/사회적 논쟁 0~20
    risk_hits = 0
    risk_hits += 2 if _has_any(text, POLICY_REG_KEYWORDS) else 0
    risk_hits += 2 if _has_any(text, LABOR_REPUTATION_KEYWORDS) else 0
    risk_hits += 1 if _has_any(text, MACRO_GEO_KEYWORDS) else 0
    risk_hits += 1 if _has_any(text, ("소송", "법원", "검찰", "조정", "분쟁", "위기", "비판", "논란", "우려")) else 0
    bd["risk"] = min(20, risk_hits * 4)
    if bd["subject"] >= 15 and bd["risk"] >= 8:
        bd["risk"] = min(20, bd["risk"] + 4)

    # 4) 매체/보도 신호
    bd["press"] = _press_score(press, title, bd["subject"])

    # 5) 톤 시그널. 주체성/리스크와 결합될 때만 크게 반영.
    tc = a.get("tone_classification") or ""
    conf = (a.get("tone_confidence") or "").lower()
    if tc == "비우호":
        bd["tone"] = 8 if (bd["subject"] >= 15 or bd["risk"] >= 8) else 3
        if conf in ("high", "상", "높음"):
            bd["tone"] = min(10, bd["tone"] + 2)
    elif tc == "양호":
        bd["tone"] = 6 if bd["subject"] >= 15 else 2

    # 6) 감점: 순수 시황/목표가 반복/무관 정치사건
    if _is_market_noise(a):
        bd["penalty"] += 25
    if _has_any(title, ("목표주가", "투자의견")) and not _has_any(text, ("전략", "공급", "HBM", "투자", "증설", "실적")):
        bd["penalty"] += 8
    if _has_any(title, MACRO_GEO_KEYWORDS) and not _has_any(text, SK_HYNIX_DIRECT + TECH_KEYWORDS + CUSTOMER_PARTNER_KEYWORDS + POLICY_REG_KEYWORDS):
        # 지정학은 중요할 수 있지만 반도체/공급망 연결이 없으면 과도한 상위 노출 방지
        bd["penalty"] += 8

    total = bd["subject"] + bd["strategy"] + bd["risk"] + bd["press"] + bd["tone"] - bd["penalty"]
    return max(0, min(100, total)), bd


def _report_class(a: dict) -> str:
    text = _article_text(a)
    if _has_any(text, SK_HYNIX_DIRECT + SK_GROUP_EXTRA):
        return "당사/그룹"
    if _has_any(text, POLICY_REG_KEYWORDS):
        return "정책/규제"
    if _has_any(text, LABOR_REPUTATION_KEYWORDS):
        return "평판/노동"
    if _has_any(text, CUSTOMER_PARTNER_KEYWORDS):
        return "고객/AI 생태계"
    if _has_any(text, RIVAL_KEYWORDS):
        return "경쟁사/업계"
    if _has_any(text, TECH_KEYWORDS):
        return "기술/제품"
    if _has_any(text, MACRO_GEO_KEYWORDS):
        return "지정학/공급망"
    if _has_any(text, MARKET_KEYWORDS):
        return "시장평가"
    return "기타"


# ──────────────────────────────────────────────────────────────
#  Prompt build / JSON parse / validation
# ──────────────────────────────────────────────────────────────
def _build_prompt(articles: list[dict], categories: dict[int, str], system_prompt: str) -> str:
    lines = [system_prompt, "", "[기사 목록]"]
    scored = []
    for a in articles:
        ps, bd = _prescore(a)
        scored.append((ps, bd, a))
    scored.sort(key=lambda x: -x[0])

    TOP_FOR_DETAIL = 25
    for idx, (ps, bd, a) in enumerate(scored):
        aid = a.get("id")
        cat = categories.get(aid, "industry")
        track = a.get("track") or ""
        press = (a.get("press") or "").replace("|", "/")[:40]
        title = (a.get("title_clean") or a.get("title") or "").replace("|", "/")[:160]
        summary = (a.get("summary") or a.get("description") or "").replace("|", "/").replace("\n", " ")[:320]
        tc = a.get("tone_classification") or "-"
        conf = a.get("tone_confidence") or "-"
        hostile = a.get("tone_hostile") or 0
        total = a.get("tone_total") or 0
        reason = (a.get("tone_reason") or "").replace("|", "/").replace("\n", " ")[:220]
        mkw = (a.get("matched_kw") or "").replace("|", "/")[:100]
        issue_key = _issue_key(a)
        report_class = _report_class(a)
        market_noise = "Y" if _is_market_noise(a) else "N"

        lines.append("")
        lines.append(
            f"[ID={aid}] rule_score={ps} "
            f"(당사{bd['subject']}+전략{bd['strategy']}+리스크{bd['risk']}+매체{bd['press']}+톤{bd['tone']}-감점{bd['penalty']}) "
            f"| category={cat} | track={track} | class={report_class} | issue_key={issue_key} | market_noise={market_noise}"
        )
        lines.append(f"  매체: {press} | 매칭키워드: {mkw}")
        lines.append(f"  제목: {title}")
        if summary:
            lines.append(f"  요약: {summary}")
        if tc and tc != "-":
            lines.append(f"  톤: {tc} (confidence={conf}, hostile={hostile}/{total})")
        if reason:
            lines.append(f"  톤 사유: {reason}")

        if idx < TOP_FOR_DETAIL and tc == "비우호":
            try:
                sents_raw = a.get("tone_sentences")
                if sents_raw:
                    sents = json.loads(sents_raw) if isinstance(sents_raw, str) else sents_raw
                    if isinstance(sents, list) and sents:
                        joined = " / ".join(str(s).replace("|", "/").replace("\n", " ")[:140] for s in sents[:5])
                        lines.append(f"  비우호 문장: {joined}")
            except Exception:
                pass
    return "\n".join(lines)


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    parsed = None
    try:
        parsed = json.loads(t)
    except json.JSONDecodeError:
        for open_c, close_c in (("{", "}"), ("[", "]")):
            start = t.find(open_c)
            end = t.rfind(close_c)
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(t[start:end + 1])
                    break
                except json.JSONDecodeError:
                    continue
    if parsed is None or isinstance(parsed, list) or not isinstance(parsed, dict):
        return None
    return parsed


def _is_transient(err: Exception) -> bool:
    s = str(err).lower()
    return any(k in s for k in ("503", "unavailable", "429", "resource_exhausted", "deadline_exceeded", "timeout"))


def _article_map(articles: list[dict]) -> dict[int, dict]:
    out = {}
    for a in articles:
        try:
            out[int(a["id"])] = a
        except Exception:
            continue
    return out


def _clean_comment(comment: str) -> str:
    c = re.sub(r"\s+", " ", str(comment or "")).strip()
    banned = [
        "긍정적인 기사", "긍정적 기사", "부정적인 기사", "부정적 맥락", "기업 가치 하락",
        "투자 심리 위축", "양호한 기사", "비우호 기사", "분류", "톤 분류"
    ]
    for b in banned:
        c = c.replace(b, "")
    return c.strip(" .") + ("." if c and not c.endswith((".", "다", "요", "함")) else "")


def _validate(payload: dict, valid_ids: set[int], articles: list[dict] | None = None,
              categories: dict[int, str] | None = None) -> dict:
    """응답 검증 + 스키마 유지 + 같은 issue_key 중복 제거."""
    article_by_id = _article_map(articles or [])
    out = {
        "top5_commentary": [],
        "company_group_top10": [],
        "industry_top10": [],
    }

    used_issue_top: set[str] = set()
    top5_obj = payload.get("top5_commentary", {})
    top_items = []
    if isinstance(top5_obj, list):
        top_items = top5_obj[:5]
    elif isinstance(top5_obj, dict):
        for i in range(1, 6):
            item = top5_obj.get(f"rank_{i}")
            if item:
                top_items.append(item)

    marker = 1
    for item in top_items:
        if not isinstance(item, dict):
            continue
        try:
            aid = int(item["article_id"])
            comment = _clean_comment(item.get("comment", ""))
            if aid not in valid_ids or not comment:
                continue
            a = article_by_id.get(aid)
            ik = _issue_key(a) if a else f"id:{aid}"
            if ik in used_issue_top:
                continue
            used_issue_top.add(ik)
            out["top5_commentary"].append({"article_id": aid, "marker_count": marker, "comment": comment})
            marker += 1
            if marker > 5:
                break
        except (KeyError, ValueError, TypeError):
            continue

    for key in ("company_group_top10", "industry_top10"):
        seen_ids: set[int] = set()
        seen_issues: set[str] = set()
        for c in payload.get(key, []) or []:
            if len(out[key]) >= 10:
                break
            try:
                aid = int(c["article_id"])
                score = int(c["score"])
                if aid not in valid_ids or aid in seen_ids:
                    continue
                a = article_by_id.get(aid)
                if a:
                    ik = _issue_key(a)
                    if ik in seen_issues:
                        continue
                    if key == "company_group_top10" and categories and not _is_company_related(a, categories):
                        # LLM이 업계 기사를 당사 섹션에 넣은 경우 방지
                        continue
                    if key == "industry_top10" and categories and _is_company_related(a, categories):
                        continue
                    if key == "industry_top10" and _is_market_noise(a):
                        continue
                    seen_issues.add(ik)
                out[key].append({"article_id": aid, "score": max(0, min(100, score))})
                seen_ids.add(aid)
            except (KeyError, ValueError, TypeError):
                continue
        out[key].sort(key=lambda x: -x["score"])
    return out


# ──────────────────────────────────────────────────────────────
#  Stage 1: 많은 기사 → 내신 후보 압축
# ──────────────────────────────────────────────────────────────
STAGE1_PROMPT = """당신은 SK하이닉스 홍보/대외협력 조직의 뉴스 브리핑 에디터입니다.
아래 기사 각각에 대해 '경영진 내신 리포트에 올릴 가치'를 0~100점으로 평가합니다.

[점수 기준]
90~100: 당사 직접 사안 또는 즉각 대응/메시지 관리가 필요한 핵심 이슈
75~89: 당사·그룹·고객사·경쟁사·정책·기술 로드맵에 중요한 영향이 있는 이슈
55~74: 업계 흐름 파악에 필요한 의미 있는 이슈
30~54: 참고 가능하지만 오늘 주요 보고 우선순위는 낮은 기사
0~29: 단순 시황, 제목만 다른 반복, 무관 기사, 생활/일반 정치 사건

[중요]
- 제목에 SK하이닉스가 있어도 목표가/주가 반복이면 과대평가하지 마십시오.
- 자사 직접 기사가 아니어도 정책, 노조/성과급, 고객사 AI 투자, 경쟁사 팹/기술, 공급망/지정학 리스크는 높게 평가할 수 있습니다.
- 단순 코스피/환율/나스닥/시총 기사만으로는 낮게 평가하십시오.

[출력]
반드시 단일 JSON 객체만 출력합니다. 설명·사유·마크다운·코드블록은 금지합니다.
키는 기사 id를 문자열로, 값은 0~100 정수 점수로 씁니다.
예: {"123":85,"124":12,"125":67}
입력된 모든 id를 빠짐없이 포함합니다.
"""


def _parse_stage1_scores(text: str) -> dict[int, int]:
    """Stage1 응답 파서.

    JSON 객체 {"123":85}를 기본으로 받는다. 과거/비정상 응답인
    JSON 배열 [{"id":123,"s":85}]과 일부 손상 텍스트도 최소 복구한다.
    """
    if not text:
        return {}
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()

    # 1) 정상 JSON 우선
    try:
        parsed = json.loads(t)
        out: dict[int, int] = {}
        if isinstance(parsed, dict):
            for k, v in parsed.items():
                try:
                    out[int(k)] = max(0, min(100, int(v)))
                except Exception:
                    continue
            return out
        if isinstance(parsed, list):  # 구버전 호환
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                try:
                    aid = int(item.get("id"))
                    s = int(item.get("s", item.get("score", 0)))
                    out[aid] = max(0, min(100, s))
                except Exception:
                    continue
            return out
    except json.JSONDecodeError:
        pass

    # 2) JSON 객체가 앞뒤 설명 때문에 깨진 경우, 가장 큰 객체 범위만 추출
    start = t.find("{")
    end = t.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(t[start:end + 1])
            if isinstance(parsed, dict):
                out = {}
                for k, v in parsed.items():
                    try:
                        out[int(k)] = max(0, min(100, int(v)))
                    except Exception:
                        continue
                return out
        except json.JSONDecodeError:
            pass

    # 3) 최후 복구: "123":85 또는 {"id":123,"s":85} 패턴
    out: dict[int, int] = {}
    for k, v in re.findall(r'"?(\d+)"?\s*:\s*(\d{1,3})', t):
        try:
            out[int(k)] = max(0, min(100, int(v)))
        except Exception:
            continue
    if out:
        return out

    for k, v in re.findall(r'\{\s*"id"\s*:\s*(\d+)\s*,\s*"s"\s*:\s*(\d{1,3})\s*\}', t):
        try:
            out[int(k)] = max(0, min(100, int(v)))
        except Exception:
            continue
    return out


def _stage1_filter(articles: list[dict], categories: dict[int, str]) -> dict[int, int]:
    if not articles:
        return {}
    try:
        from google import genai
        from google.genai import types as gtypes
    except ImportError:
        logger.error("[Stage1] google-genai 미설치")
        return {a["id"]: _prescore(a)[0] for a in articles if "id" in a}

    import os
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.warning("[Stage1] GEMINI_API_KEY 없음 - 규칙 점수 fallback")
        return {a["id"]: _prescore(a)[0] for a in articles if "id" in a}

    # JSON 배열 [{id,s}]는 8192 토큰 근처에서 잘려 정규식 복구가 반복될 수 있다.
    # 객체 맵 {"id":score}로 출력 토큰을 줄이고, 배치 크기도 낮춰 truncate 가능성을 줄인다.
    BATCH_SIZE = 300
    client = genai.Client(api_key=api_key)
    all_scores: dict[int, int] = {}
    batches = [articles[i:i + BATCH_SIZE] for i in range(0, len(articles), BATCH_SIZE)]
    logger.info(f"[Stage1] {len(articles)}건 → {len(batches)}배치 ({BATCH_SIZE}건씩, compact-json-map)")

    for bi, batch in enumerate(batches, 1):
        batch_by_id: dict[int, dict] = {}
        lines = []
        for a in batch:
            try:
                aid = int(a.get("id"))
            except Exception:
                continue
            batch_by_id[aid] = a
            cat = categories.get(aid, "industry")
            title = (a.get("title_clean") or a.get("title") or "")[:90]
            summary = (a.get("summary") or a.get("description") or "")[:120]
            tone = a.get("tone_classification") or "-"
            press = (a.get("press") or "-")[:20]
            track = a.get("track") or "-"
            # Stage1은 LLM 점수만 받는다. prescore/규칙 점수는 섞지 않아 후보 압축 노이즈를 줄인다.
            lines.append(f"{aid}|{cat}|{track}|{tone}|{press}|{title} :: {summary}")
        full_prompt = STAGE1_PROMPT + "\n[기사 목록]\n" + "\n".join(lines)

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
            parsed_scores = _parse_stage1_scores(text)
            if len(parsed_scores) < max(1, int(len(batch_by_id) * 0.9)):
                logger.warning(
                    f"[Stage1] 배치 {bi} 응답 누락 많음: 입력 {len(batch_by_id)}건 → 파싱 {len(parsed_scores)}건"
                )
            else:
                logger.info(f"[Stage1] 배치 {bi} JSON 파싱 성공: {len(parsed_scores)}/{len(batch_by_id)}건")

            for aid in batch_by_id.keys():
                llm_s = parsed_scores.get(aid)
                # 누락분은 0점으로 둔다. 잘릴 정도의 후순위 응답은 Stage2 후보에서 자연스럽게 밀리게 한다.
                all_scores[aid] = max(0, min(100, int(llm_s))) if llm_s is not None else 0
            logger.info(f"[Stage1] 배치 {bi}/{len(batches)} 완료")
        except Exception as e:
            logger.error(f"[Stage1] 배치 {bi} 실패: {e}")
            for aid in batch_by_id.keys():
                all_scores[aid] = 0

    for a in articles:
        if "id" in a:
            all_scores.setdefault(int(a["id"]), 0)
    return all_scores

def _select_top_by_track(articles: list[dict], scores: dict[int, int], per_track: int = 120) -> list[dict]:
    """Stage2 입력 후보를 track별/이슈별로 다양하게 보존."""
    def sort_key(a: dict):
        aid = int(a.get("id", 0))
        return (scores.get(aid, 0), a.get("collected_at") or a.get("pub_date") or "")

    buckets = {
        "monitor": [a for a in articles if (a.get("track") or "") == "monitor"],
        "reference": [a for a in articles if (a.get("track") or "") != "monitor"],
    }
    selected: list[dict] = []
    for name, bucket in buckets.items():
        bucket.sort(key=sort_key, reverse=True)
        seen_issues: set[str] = set()
        kept: list[dict] = []
        # 1차: 이슈 중복 제거하며 보존
        for a in bucket:
            ik = _issue_key(a)
            if ik in seen_issues:
                continue
            kept.append(a)
            seen_issues.add(ik)
            if len(kept) >= per_track:
                break
        # 2차: 너무 적으면 중복 허용해 보충
        if len(kept) < min(per_track, len(bucket)):
            kept_ids = {x.get("id") for x in kept}
            for a in bucket:
                if a.get("id") not in kept_ids:
                    kept.append(a)
                if len(kept) >= per_track:
                    break
        selected.extend(kept)
        logger.info(f"[Stage1] {name}: 입력 {len(bucket)}건 → 후보 {len(kept)}건")
    return selected


# ──────────────────────────────────────────────────────────────
#  Fallback / 보정
# ──────────────────────────────────────────────────────────────
def _sort_articles_for_report(articles: list[dict], categories: dict[int, str], section: str) -> list[dict]:
    scored = []
    for a in articles:
        if "id" not in a:
            continue
        if section == "company" and not _is_company_related(a, categories):
            continue
        if section == "industry" and _is_company_related(a, categories):
            continue
        if section == "industry" and _is_market_noise(a):
            continue
        s, bd = _prescore(a)
        # 섹션별 가중
        if section == "company":
            s += 8 if bd["subject"] >= 20 else 0
        elif section == "industry":
            s += 6 if (bd["strategy"] + bd["risk"] >= 16) else 0
        scored.append((s, a))
    scored.sort(key=lambda x: (x[0], x[1].get("collected_at") or x[1].get("pub_date") or ""), reverse=True)
    return [a for _, a in scored]


def _dedup_articles(articles: list[dict], limit: int) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for a in articles:
        ik = _issue_key(a)
        if ik in seen:
            continue
        seen.add(ik)
        out.append(a)
        if len(out) >= limit:
            break
    return out


def _fallback_comment(a: dict) -> str:
    title = _safe_text(a.get("title_clean") or a.get("title"))
    summary = _safe_text(a.get("summary") or a.get("description"))
    text = _safe_text(title, summary)
    cls = _report_class(a)

    if cls == "당사/그룹":
        if _has_any(text, ("보도자료", "선정", "수상", "르포", "다큐", "청년", "윤리", "안전보건")):
            return f"당사 관련 보도가 이어지며 {title} 이슈가 조명됐습니다. 언론은 당사의 기술 경쟁력과 조직·평판 측면의 메시지를 함께 부각했습니다."
        if _has_any(text, ("투자", "생산", "공장", "팹", "클러스터", "M15X", "용인")):
            return f"당사의 생산·투자 계획과 관련해 {title} 내용이 보도됐습니다. 향후 HBM 등 차세대 제품 공급 역량과 중장기 성장성에 대한 시장 관심이 이어질 수 있습니다."
        return f"당사 및 그룹 관련 주요 이슈로 {title} 내용이 보도됐습니다. 경영진 보고 관점에서 사실관계와 후속 보도 흐름을 점검할 필요가 있습니다."
    if cls == "정책/규제":
        return f"정책·규제 환경과 관련해 {title} 내용이 보도됐습니다. 반도체 산업 지원, 비용 구조, 투자 여건에 미칠 영향을 점검할 필요가 있습니다."
    if cls == "평판/노동":
        return f"노동·보상·평판 이슈와 관련해 {title} 보도가 나왔습니다. 당사와 업계 전반의 보상 논의나 여론 흐름으로 확산될 가능성을 살펴볼 필요가 있습니다."
    if cls == "고객/AI 생태계":
        return f"주요 AI 생태계 기업과 관련해 {title} 내용이 보도됐습니다. 고객사의 투자 방향과 AI 인프라 전략 변화가 메모리 수요에 미칠 영향을 주목할 필요가 있습니다."
    if cls == "경쟁사/업계":
        return f"경쟁사 및 업계 동향으로 {title} 내용이 보도됐습니다. 당사 사업 환경과 경쟁 구도에 미칠 영향을 점검할 필요가 있습니다."
    if cls == "기술/제품":
        return f"반도체 기술·제품 흐름과 관련해 {title} 내용이 보도됐습니다. 차세대 메모리 로드맵과 고객 수요 변화 측면에서 참고할 만한 이슈입니다."
    if cls == "지정학/공급망":
        return f"지정학·공급망 변수로 {title} 내용이 보도됐습니다. 에너지·물류·고객 투자심리에 미칠 파장을 모니터링할 필요가 있습니다."
    return f"업계 참고 이슈로 {title} 내용이 보도됐습니다. 당사 관련성 및 후속 확산 여부를 지켜볼 필요가 있습니다."


def _fallback(articles: list[dict], categories: dict[int, str]) -> dict:
    logger.warning("⚠️ 임팩트 평가 fallback (규칙 기반 이슈 선별)")
    company = _dedup_articles(_sort_articles_for_report(articles, categories, "company"), 10)
    industry = _dedup_articles(_sort_articles_for_report(articles, categories, "industry"), 10)

    # TOP 이슈는 company/industry 상위 후보를 섞되, 당사 직접성과 외부 리스크를 균형 있게 반영
    pool = []
    for a in company[:8] + industry[:8]:
        s, bd = _prescore(a)
        # comment 상위는 단순 시장평가보다 전략/리스크/평판 이슈 선호
        s += min(12, bd["strategy"] // 2 + bd["risk"] // 2)
        if _issue_family(a) in {"market_rating", "market_general"}:
            s -= 10
        pool.append((s, a))
    pool.sort(key=lambda x: x[0], reverse=True)
    top_src = _dedup_articles([a for _, a in pool], 5)

    return {
        "top5_commentary": [
            {"article_id": int(a["id"]), "marker_count": i + 1, "comment": _fallback_comment(a)}
            for i, a in enumerate(top_src[:5])
        ],
        "company_group_top10": [
            {"article_id": int(a["id"]), "score": _prescore(a)[0]} for a in company[:10]
        ],
        "industry_top10": [
            {"article_id": int(a["id"]), "score": _prescore(a)[0]} for a in industry[:10]
        ],
    }


def _fill_missing(result: dict, articles: list[dict], categories: dict[int, str]) -> dict:
    """LLM 결과가 비었거나 필터링으로 부족해진 경우 규칙 기반 후보로 보충."""
    fallback = _fallback(articles, categories)

    # top5 보충: 기존 이슈와 중복되지 않게 marker 재정렬
    article_by_id = _article_map(articles)
    seen_top_issues = set()
    for item in result.get("top5_commentary", []):
        a = article_by_id.get(item.get("article_id"))
        if a:
            seen_top_issues.add(_issue_key(a))
    for item in fallback["top5_commentary"]:
        if len(result["top5_commentary"]) >= 5:
            break
        a = article_by_id.get(item["article_id"])
        ik = _issue_key(a) if a else f"id:{item['article_id']}"
        if ik in seen_top_issues:
            continue
        seen_top_issues.add(ik)
        result["top5_commentary"].append(item)
    for i, item in enumerate(result["top5_commentary"][:5], start=1):
        item["marker_count"] = i
    result["top5_commentary"] = result["top5_commentary"][:5]

    for key in ("company_group_top10", "industry_top10"):
        seen_ids = {x["article_id"] for x in result.get(key, [])}
        seen_issues = set()
        for x in result.get(key, []):
            a = article_by_id.get(x["article_id"])
            if a:
                seen_issues.add(_issue_key(a))
        for item in fallback[key]:
            if len(result[key]) >= 10:
                break
            if item["article_id"] in seen_ids:
                continue
            a = article_by_id.get(item["article_id"])
            ik = _issue_key(a) if a else f"id:{item['article_id']}"
            if ik in seen_issues:
                continue
            result[key].append(item)
            seen_ids.add(item["article_id"])
            seen_issues.add(ik)
        result[key] = sorted(result[key][:10], key=lambda x: -x["score"])
    return result


# ──────────────────────────────────────────────────────────────
#  Public API
# ──────────────────────────────────────────────────────────────
def evaluate(articles: list[dict], categories: dict[int, str], settings: dict) -> dict:
    """LLM 호출로 임팩트 평가. 실패 시 규칙 기반 fallback."""
    if not articles:
        return {"top5_commentary": [], "company_group_top10": [], "industry_top10": []}

    # Stage 1: 많을 때만 압축하되, 이슈 다양성 보존
    if len(articles) > 200:
        logger.info(f"[Stage1] 전체 {len(articles)}건 → 필터링 시작")
        scores = _stage1_filter(articles, categories)
        articles = _select_top_by_track(articles, scores, per_track=120)
        logger.info(f"[Stage1] 필터 결과 {len(articles)}건 → Stage2 진행")

    valid_ids = {int(a["id"]) for a in articles if "id" in a}
    system_prompt = settings.get("daily_report_impact_prompt", DEFAULT_IMPACT_PROMPT)
    prompt = _build_prompt(articles, categories, system_prompt)

    client = get_client()
    if client is None:
        logger.warning("Gemini 미사용 — 임팩트 평가 fallback")
        return _fallback(articles, categories)

    model = settings.get("gpt_model_tone", DEFAULT_MODEL)

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "top5_commentary": {
                "type": "OBJECT",
                "properties": {
                    f"rank_{i}": {
                        "type": "OBJECT",
                        "properties": {
                            "article_id": {"type": "INTEGER"},
                            "comment": {"type": "STRING"},
                        },
                        "required": ["article_id", "comment"],
                    } for i in range(1, 6)
                },
                "required": ["rank_1"],
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
        "temperature": 0.15,
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

            result = _validate(payload, valid_ids, articles=articles, categories=categories)
            result = _fill_missing(result, articles, categories)

            logger.info(
                f"✅ 임팩트 평가 완료: 톱={len(result['top5_commentary'])}, "
                f"당사·그룹={len(result['company_group_top10'])}, 업계동향={len(result['industry_top10'])}"
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

    logger.error(f"임팩트 평가 최종 실패: {last_err}")
    return _fallback(articles, categories)
