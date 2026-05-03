# app/services/recipient_filter.py
"""
수신자 권한 매칭.

기사의 (tier, tone_level)에 따라 어떤 수신자가 받을지 결정합니다.
recipients 테이블의 receive_* 플래그를 보고 매칭하므로, 임원에게는
경고만, 실무자에게는 전부 보내는 식의 정책이 가능합니다.

매칭 규칙:
    TIER 1 (하이닉스·삼성)
        - 경고 → receive_tier1_warn 가 1인 수신자
        - 주의 → receive_tier1_watch 가 1
        - 양호 → receive_tier1_good  가 1
        - tone_level이 비어있으면 양호로 간주
    TIER 2 (메모리·AI 칩)
        → receive_tier2 가 1인 수신자
    TIER 3 (빅테크·경쟁사)
        → receive_tier3 가 1인 수신자
"""

import logging

logger = logging.getLogger(__name__)


def match_recipients(article: dict, recipients: list[dict]) -> list[dict]:
    """
    기사를 받을 수신자만 필터링해 반환.

    Args:
        article: tier, tone_level 키 사용
        recipients: recipient_list_active() 결과

    Returns:
        매칭된 수신자 dict 리스트.
    """
    tier = int(article.get("tier", 3))
    tone_level = article.get("tone_level") or "양호"

    matched = []
    for r in recipients:
        if tier == 1:
            if tone_level == "경고" and r.get("receive_tier1_warn"):
                matched.append(r)
            elif tone_level == "주의" and r.get("receive_tier1_watch"):
                matched.append(r)
            elif tone_level == "양호" and r.get("receive_tier1_good"):
                matched.append(r)
        elif tier == 2:
            if r.get("receive_tier2"):
                matched.append(r)
        elif tier == 3:
            if r.get("receive_tier3"):
                matched.append(r)

    logger.info(
        f"  👥 수신자 매칭: tier={tier} tone={tone_level} "
        f"→ {len(matched)}/{len(recipients)}명"
    )
    return matched
