"""
관련성 필터 (규칙 기반).

STEP 4A-1:
- 메이저 언론사 + [단독] 패턴이면 즉시 통과
- 화이트리스트 → 블랙리스트

STEP-COST-2: Gemini 배치 분류 단계 폐기. LLM은 기사를 '제거'만 할 수 있어
놓침 위험만 만들고(로그상 후보의 약 3% 제거), 10분마다 같은 기사를 반복
분류하며 비용을 썼다. 규칙으로 결정되지 않은 기사는 모두 통과.

STEP-COST-2 검수 반영: 제목·description에 SK그룹/SK하이닉스 언급이 있으면
영문 제목 제거·블랙리스트를 모두 면제 (예: "SK hynix unveils ..." 영문 기사,
"재계 총수들 야구 관람"(description에 최태원), "SK에너지 골프 대회 후원").

처리 순서:
    1. SK 언급(제목+description) → 무조건 통과
    2. 영문 전용 기사 제거
    3. 메이저 언론사 + 단독 자동 통과
    4. 화이트리스트 키워드 통과
    5. 도메인/제목 블랙리스트 차단
    6. 나머지는 통과
"""

import logging
import re

logger = logging.getLogger(__name__)


# ── 화이트리스트 ──────────────────────────────────────────────
WHITELIST_KEYWORDS = [
    # SK하이닉스 직접
    "하이닉스", "sk하이닉스", "skhynix", "hynix", "솔리다임",
    "곽노정",
    # SK 그룹 지주·계열사
    "sk텔레콤", "skt", "sk(주)", "sk주식회사",
    "sk스퀘어", "sk이노베이션", "sk온", "sk가스",
    "sk디스커버리", "sk바이오팜", "sk바이오사이언스",
    "sk네트웍스", "sk실트론", "sk시그넷",
    "sk그룹",
    # 그룹 임원
    "최태원", "최창원", "최재원",
    # 경쟁사·산업
    "삼성전자", "samsung",
    "hbm", "고대역폭메모리",
    "d램", "dram", "낸드", "nand",
    "엔비디아", "nvidia",
    "tsmc", "파운드리", "마이크론",
    "반도체",
]

# ── SK그룹·SK하이닉스 언급 (제목+description) → 필터 면제 ─────────────
# 영문 토큰은 단어 경계로 검사 ("desktop" 속 "skt" 같은 오탐 방지)
SK_KEYWORDS = [
    "sk하이닉스", "하이닉스", "skhynix", "sk hynix", "hynix", "솔리다임", "solidigm", "곽노정",
    "sk그룹", "sk(주)", "sk주식회사", "sk스퀘어", "sk이노베이션", "sk온", "sk텔레콤", "skt",
    "sk가스", "sk디스커버리", "sk바이오팜", "sk바이오사이언스", "sk네트웍스", "sk실트론",
    "sk시그넷", "sk에너지", "skc", "sk에코플랜트", "sk케미칼", "sk브로드밴드", "sk증권",
    "sk e&s", "sk이엔에스", "sk매직", "sk쉴더스", "sk엔무브", "sk ax", "sk플라즈마",
    "sk에어플러스", "sk머티리얼즈", "sk지오센트릭", "sk아이이테크놀로지", "sk바이오텍",
    "최태원", "최창원", "최재원",
]
_SK_PATTERNS = [
    re.compile(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])") if k.isascii() else re.compile(re.escape(k))
    for k in SK_KEYWORDS
]


def _mentions_sk(title: str, description: str) -> bool:
    text = f"{title} {description}".lower()
    return any(p.search(text) for p in _SK_PATTERNS)


# ── 메이저 언론사 도메인 ──────────────────────────────────────
MAJOR_PRESS_DOMAINS = [
    "chosun.com", "joongang.co.kr", "donga.com",
    "mk.co.kr", "hankyung.com", "sedaily.com",
    "fnnews.com", "yna.co.kr", "news1.kr", "newsis.com",
    "mt.co.kr", "edaily.co.kr", "hani.co.kr",
    "khan.co.kr", "heraldcorp.com", "asiae.co.kr", "munhwa.com",
]

EXCLUSIVE_PATTERNS = [
    r"\[단독\]", r"<단독>", r"단독:", r"【단독】", r"\(단독\)",
]

def _clean_title(title: str) -> str:
    return re.sub(r"<[^>]+>", "", title or "").strip()


def _is_whitelisted(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in WHITELIST_KEYWORDS)


def _is_major_exclusive(title: str, link: str) -> bool:
    """메이저 언론사 + 단독 패턴이면 True."""
    link_lower = link.lower()
    if not any(d in link_lower for d in MAJOR_PRESS_DOMAINS):
        return False
    return any(re.search(p, title) for p in EXCLUSIVE_PATTERNS)


def _is_english_only(title: str) -> bool:
    if not title:
        return False
    if re.search(r"[\uAC00-\uD7A3]", title):
        return False
    alpha_count = sum(1 for c in title if c.isalpha())
    if alpha_count == 0:
        return False
    english_count = sum(1 for c in title if "A" <= c.upper() <= "Z")
    return (english_count / alpha_count) >= 0.6


def _is_blacklisted(title: str, link: str,
                    domain_bl: list, title_bl: list) -> bool:
    if _is_whitelisted(title):
        return False

    link_lower = link.lower()
    if any(d in link_lower for d in domain_bl):
        return True

    title_lower = title.lower()
    for kw in title_bl:
        m = re.search(re.escape(kw), title_lower)
        if not m:
            continue
        before = title_lower[m.start() - 1] if m.start() > 0 else " "
        after  = title_lower[m.end()]       if m.end() < len(title_lower) else " "
        if ("\uAC00" <= before <= "\uD7A3") or ("\uAC00" <= after <= "\uD7A3"):
            continue
        return True

    return False


def filter_relevant(articles: list[dict], settings: dict) -> list[dict]:
    if not articles:
        return []

    if not settings.get("relevance_filter_enabled", True):
        logger.info("ℹ️ 관련성 필터 비활성화 — 전체 통과")
        return articles

    domain_bl = [d.lower() for d in settings.get("domain_blacklist", [])]
    title_bl  = settings.get("title_blacklist", [])

    sk_pass      = []  # SK 언급 → 필터 면제 (STEP-COST-2)
    auto_pass    = []  # 메이저+단독 자동 통과
    whitelisted  = []
    undecided    = []  # 규칙으로 결정 안 된 기사 → 통과 (STEP-COST-2)
    removed_en   = 0
    removed_bl   = 0

    for a in articles:
        title = _clean_title(a.get("title", ""))
        link  = a.get("link") or a.get("originallink", "")

        # 0단계: SK그룹/SK하이닉스 언급 → 무조건 통과
        if _mentions_sk(title, _clean_title(a.get("description", ""))):
            sk_pass.append(a)
            continue

        # 1단계: 영문 전용 제거
        if _is_english_only(title):
            removed_en += 1
            continue

        # 2단계: 메이저 언론사 + 단독 자동 통과
        if _is_major_exclusive(title, link):
            auto_pass.append(a)
            logger.info(f"  ⭐ 메이저 단독 자동통과: {title[:40]}")
            continue

        # 3단계: 화이트리스트
        if _is_whitelisted(title):
            whitelisted.append(a)
            continue

        # 4단계: 블랙리스트
        if _is_blacklisted(title, link, domain_bl, title_bl):
            removed_bl += 1
            continue

        undecided.append(a)

    final = sk_pass + auto_pass + whitelisted + undecided
    logger.info(
        f"🏷️ SK언급: {len(sk_pass)} | "
        f"🌐 영문제거: {removed_en} | "
        f"⭐ 메이저단독: {len(auto_pass)} | "
        f"✅ 화이트리스트: {len(whitelisted)} | "
        f"🚫 블랙리스트: {removed_bl} | "
        f"➡️ 규칙 미결정 통과: {len(undecided)} | "
        f"🏁 최종 통과: {len(final)}"
    )
    return final
