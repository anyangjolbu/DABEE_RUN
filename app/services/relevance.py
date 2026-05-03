"""
관련성 필터 (4단계).

STEP 4A-1:
- 메이저 언론사 + [단독] 패턴이면 즉시 통과 (Gemini 호출 없이)
- 화이트리스트 → 블랙리스트 → Gemini 배치 분류

처리 순서:
    1. 영문 전용 기사 제거
    2. 메이저 언론사 + 단독 자동 통과
    3. 화이트리스트 키워드 통과
    4. 도메인/제목 블랙리스트 차단
    5. 위에서 결정 안 된 기사만 Gemini에게 일괄 분류
"""

import logging
import re

from app.services.gemini_client import get_client

logger = logging.getLogger(__name__)


# ── 화이트리스트 ──────────────────────────────────────────────
WHITELIST_KEYWORDS = [
    "하이닉스", "sk하이닉스", "skhynix", "hynix", "솔리다임",
    "곽노정", "최태원",
    "삼성전자", "samsung",
    "hbm", "고대역폭메모리",
    "d램", "dram", "낸드", "nand",
    "엔비디아", "nvidia",
    "tsmc", "파운드리", "마이크론",
    "반도체",
]

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

BATCH_SIZE = 50


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


def _gemini_classify_batch(batch: list[dict]) -> list[dict]:
    if not batch:
        return []

    client = get_client()
    if client is None:
        logger.warning("Gemini 미사용 — 모든 기사 통과 처리")
        return batch

    titles_text = "\n".join(
        f"{i+1}. {_clean_title(a.get('title', ''))}"
        for i, a in enumerate(batch)
    )

    prompt = (
        "아래 기사 제목 목록을 보고, 각 번호에 대해 판단하시오.\n\n"
        "YES로 판단하는 경우:\n"
        "- 반도체, 메모리(HBM·D램·낸드), AI칩, 파운드리 관련\n"
        "- IT 기업(애플·구글·MS·메타·아마존·엔비디아·TSMC 등) 사업·실적\n"
        "- 관련 기업의 투자·인수합병·공장·인력 뉴스\n"
        "- 반도체 관련 정부 정책, 수출규제, 공급망\n"
        "- SK·SK하이닉스·곽노정·최태원 관련 모든 뉴스\n\n"
        "NO로 판단하는 경우:\n"
        "- 스포츠(야구·축구·골프·올림픽 등)\n"
        "- 연예·드라마·아이돌·배우 사생활\n"
        "- 날씨·부동산·요리·여행·패션 단순 기사\n\n"
        "출력 형식: 번호:YES 또는 번호:NO (한 줄에 하나씩, 다른 텍스트 없이)\n\n"
        f"{titles_text}"
    )

    try:
        resp = client.models.generate_content(
            model="gemini-flash-lite-latest",
            contents=prompt,
            config={"max_output_tokens": len(batch) * 12, "temperature": 0},
        )
        answer = resp.text.strip()
    except Exception as e:
        logger.error(f"❌ Gemini 호출 실패 (전체 통과 처리): {e}")
        return batch

    result_map: dict[int, bool] = {}
    for line in answer.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        idx_str, val_str = line.split(":", 1)
        try:
            idx = int(idx_str.strip())
            result_map[idx] = val_str.strip().upper().startswith("YES")
        except ValueError:
            continue

    relevant = []
    removed_count = 0
    for i, article in enumerate(batch):
        if result_map.get(i + 1, True):
            relevant.append(article)
        else:
            removed_count += 1
            logger.info(f"  ✂️ Gemini 제외: {_clean_title(article.get('title', ''))[:40]}")

    logger.info(f"  → 배치 {len(batch)}건 중 {removed_count}건 제거, {len(relevant)}건 통과")
    return relevant


def filter_relevant(articles: list[dict], settings: dict) -> list[dict]:
    if not articles:
        return []

    if not settings.get("relevance_filter_enabled", True):
        logger.info("ℹ️ 관련성 필터 비활성화 — 전체 통과")
        return articles

    domain_bl = [d.lower() for d in settings.get("domain_blacklist", [])]
    title_bl  = settings.get("title_blacklist", [])

    auto_pass    = []  # 메이저+단독 자동 통과
    whitelisted  = []
    to_gemini    = []
    removed_en   = 0
    removed_bl   = 0

    for a in articles:
        title = _clean_title(a.get("title", ""))
        link  = a.get("link") or a.get("originallink", "")

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

        to_gemini.append(a)

    logger.info(
        f"🌐 영문제거: {removed_en} | "
        f"⭐ 메이저단독: {len(auto_pass)} | "
        f"✅ 화이트리스트: {len(whitelisted)} | "
        f"🚫 블랙리스트: {removed_bl} | "
        f"🤖 Gemini 후보: {len(to_gemini)}"
    )

    if not to_gemini:
        final = auto_pass + whitelisted
        logger.info(f"🏁 최종 통과: {len(final)}건 (Gemini 호출 없음)")
        return final

    relevant_gemini: list[dict] = []
    total_batches = (len(to_gemini) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(total_batches):
        start = i * BATCH_SIZE
        batch = to_gemini[start : start + BATCH_SIZE]
        logger.info(f"🤖 Gemini 배치 [{i+1}/{total_batches}] — {len(batch)}건")
        relevant_gemini.extend(_gemini_classify_batch(batch))

    final = auto_pass + whitelisted + relevant_gemini
    logger.info(
        f"🏁 최종 통과: {len(final)}건 "
        f"(메이저단독 {len(auto_pass)} + 화이트리스트 {len(whitelisted)} + Gemini통과 {len(relevant_gemini)})"
    )
    return final