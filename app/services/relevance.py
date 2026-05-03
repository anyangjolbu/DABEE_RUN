# app/services/relevance.py
"""
관련성 필터 (3단계).

네이버 API는 키워드 매칭이라 "삼성"으로 검색하면 "삼성 라이온즈" 같은
야구 기사가 잔뜩 섞여 들어옵니다. 이 모듈이 반도체·IT와 무관한
기사를 걸러냅니다.

처리 순서:
    1. 영문 전용 기사 제거 (한국 매체 위주 운영)
    2. 화이트리스트 키워드 통과 (반도체·메모리·IT 핵심)
    3. 도메인/제목 블랙리스트 차단
    4. 위에서 결정 안 된 기사만 Gemini에게 일괄 분류 요청

Gemini는 비용·속도가 비싸므로 마지막에만 호출하고, 한 번에 50건씩
배치로 묶어 호출 횟수를 줄입니다.
"""

import logging
import re

from app.services.gemini_client import get_client

logger = logging.getLogger(__name__)


# ── 화이트리스트 ──────────────────────────────────────────────────────
# 이 단어가 제목에 있으면 반도체·IT 기사로 간주하고 즉시 통과.
# Gemini 호출 없이 빠르게 처리되어 비용 절감.
WHITELIST_KEYWORDS = [
    "하이닉스", "sk하이닉스", "skhynix", "hynix", "솔리다임",
    "삼성전자", "samsung",
    "hbm", "고대역폭메모리",
    "d램", "dram", "낸드", "nand",
    "엔비디아", "nvidia",
    "tsmc", "파운드리",
    "반도체",
]

# Gemini 배치 호출 단위 (한 번에 분류할 기사 수).
# 50개를 넘기면 토큰 제한에 걸릴 수 있고, 너무 작으면 호출 횟수가
# 늘어 비용이 증가합니다. 50이 경험상 최적.
BATCH_SIZE = 50


# ── 헬퍼 함수 ────────────────────────────────────────────────────────
def _clean_title(title: str) -> str:
    """네이버 API 응답의 <b>...</b> 태그 제거."""
    return re.sub(r"<[^>]+>", "", title or "").strip()


def _is_whitelisted(title: str) -> bool:
    """제목에 화이트리스트 키워드가 하나라도 있으면 True."""
    t = title.lower()
    return any(kw in t for kw in WHITELIST_KEYWORDS)


def _is_english_only(title: str) -> bool:
    """
    영문 전용 기사 판별.
    한글이 한 글자라도 있으면 False.
    알파벳 비율이 60% 이상이면 영문 전용으로 판단.
    """
    if not title:
        return False
    if re.search(r"[\uAC00-\uD7A3]", title):  # 한글 한 글자라도 있으면 통과
        return False

    alpha_count = sum(1 for c in title if c.isalpha())
    if alpha_count == 0:
        return False

    english_count = sum(1 for c in title if "A" <= c.upper() <= "Z")
    return (english_count / alpha_count) >= 0.6


def _is_blacklisted(title: str, link: str,
                    domain_bl: list, title_bl: list) -> bool:
    """
    도메인/제목 블랙리스트 매칭.
    화이트리스트가 우선이므로 화이트리스트 통과 기사는 검사하지 않음.

    제목 블랙리스트는 단어 경계를 고려합니다. 예를 들어 "야구"가
    블랙리스트에 있을 때 "야구장 옆 반도체 공장"의 "야구"는 차단하지만,
    "(이)야구를 계속한다" 같은 어절 내 출현은 차단하지 않도록
    앞뒤 한 글자가 한글이면 무시합니다.
    """
    if _is_whitelisted(title):
        return False

    # 도메인 차단 (단순 substring)
    link_lower = link.lower()
    if any(d in link_lower for d in domain_bl):
        return True

    # 제목 차단 (한글 단어 경계 보호)
    title_lower = title.lower()
    for kw in title_bl:
        m = re.search(re.escape(kw), title_lower)
        if not m:
            continue
        before = title_lower[m.start() - 1] if m.start() > 0 else " "
        after  = title_lower[m.end()]       if m.end() < len(title_lower) else " "
        # 앞뒤가 한글 음절이면 어절 내 출현 → 무시
        if ("\uAC00" <= before <= "\uD7A3") or ("\uAC00" <= after <= "\uD7A3"):
            continue
        return True

    return False


# ── Gemini 배치 분류 ─────────────────────────────────────────────────
def _gemini_classify_batch(batch: list[dict]) -> list[dict]:
    """
    배치를 Gemini에게 보내 YES(반도체/IT 관련)/NO 판정.
    실패 시 안전 측면에서 전부 통과 처리.
    """
    if not batch:
        return []

    client = get_client()
    if client is None:
        # 클라이언트 없으면 전부 통과
        logger.warning("Gemini 미사용 — 모든 기사 통과 처리")
        return batch

    # 번호 매겨서 한 번에 보내기
    titles_text = "\n".join(
        f"{i+1}. {_clean_title(a.get('title', ''))}"
        for i, a in enumerate(batch)
    )

    prompt = (
        "아래 기사 제목 목록을 보고, 각 번호에 대해 판단하시오.\n\n"
        "YES로 판단하는 경우:\n"
        "- 반도체, 메모리(HBM·D램·낸드), AI칩, 파운드리, 디스플레이, 배터리 관련\n"
        "- IT 기업(애플·구글·MS·메타·아마존·엔비디아·TSMC 등) 사업·실적·전략\n"
        "- 관련 기업의 투자·인수합병·공장·인력 뉴스\n"
        "- 반도체 관련 정부 정책, 수출규제, 공급망\n\n"
        "NO로 판단하는 경우:\n"
        "- 스포츠(야구·축구·골프·올림픽 등) 경기·선수 소식\n"
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

    # 응답 파싱 — "1:YES\n2:NO\n..."
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
        # 응답 누락분은 안전하게 통과 (False positive < False negative)
        if result_map.get(i + 1, True):
            relevant.append(article)
        else:
            removed_count += 1
            logger.info(f"  ✂️ Gemini 제외: {_clean_title(article.get('title', ''))[:40]}")

    logger.info(f"  → 배치 {len(batch)}건 중 {removed_count}건 제거, {len(relevant)}건 통과")
    return relevant


# ── 메인 진입점 ──────────────────────────────────────────────────────
def filter_relevant(articles: list[dict], settings: dict) -> list[dict]:
    """
    기사 리스트를 3단계로 필터링해 반도체·IT 관련 기사만 반환.

    Args:
        articles: 네이버 API 수집 결과
        settings: settings.json (relevance_filter_enabled, blacklist 등 사용)

    Returns:
        관련성 통과 기사만 포함한 리스트.
    """
    if not articles:
        return []

    # 필터 비활성화 — 전부 통과
    if not settings.get("relevance_filter_enabled", True):
        logger.info("ℹ️ 관련성 필터 비활성화 — 전체 통과")
        return articles

    domain_bl = [d.lower() for d in settings.get("domain_blacklist", [])]
    title_bl  = settings.get("title_blacklist", [])

    whitelisted = []
    to_gemini   = []
    removed_en  = 0
    removed_bl  = 0

    for a in articles:
        title = _clean_title(a.get("title", ""))
        link  = a.get("link") or a.get("originallink", "")

        # 1단계: 영문 전용 제거
        if _is_english_only(title):
            removed_en += 1
            logger.debug(f"  🌐 영문 전용 제거: {title[:40]}")
            continue

        # 2단계: 화이트리스트 통과
        if _is_whitelisted(title):
            whitelisted.append(a)
            continue

        # 3단계: 블랙리스트 차단
        if _is_blacklisted(title, link, domain_bl, title_bl):
            removed_bl += 1
            logger.debug(f"  🚫 블랙리스트 제거: {title[:40]}")
            continue

        # 위 3단계에서 결정 안 됨 → Gemini 후보
        to_gemini.append(a)

    logger.info(
        f"🌐 영문제거: {removed_en} | "
        f"✅ 화이트리스트: {len(whitelisted)} | "
        f"🚫 블랙리스트: {removed_bl} | "
        f"🤖 Gemini 후보: {len(to_gemini)}"
    )

    if not to_gemini:
        logger.info(f"🏁 최종 통과: {len(whitelisted)}건 (Gemini 호출 없음)")
        return whitelisted

    # 4단계: Gemini 배치 분류
    relevant_gemini: list[dict] = []
    total_batches = (len(to_gemini) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(total_batches):
        start = i * BATCH_SIZE
        batch = to_gemini[start : start + BATCH_SIZE]
        logger.info(f"🤖 Gemini 배치 [{i+1}/{total_batches}] — {len(batch)}건")
        relevant_gemini.extend(_gemini_classify_batch(batch))

    final = whitelisted + relevant_gemini
    logger.info(
        f"🏁 최종 통과: {len(final)}건 "
        f"(화이트리스트 {len(whitelisted)} + Gemini통과 {len(relevant_gemini)})"
    )
    return final
