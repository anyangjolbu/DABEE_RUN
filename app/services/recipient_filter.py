"""
수신자 매칭.

STEP 4A-1:
- monitor 트랙: tone_classification(비우호/일반/미분석)에 따라
  receive_monitor_hostile / receive_monitor_normal로 매칭
  (현재는 호환 차원에서 receive_tier1_warn / receive_tier1_good에 매핑)
- reference 트랙: receive_reference=1인 수신자만
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def match_recipients(
    article:    dict,
    recipients: list[dict],
    track:      str = "monitor",
    tone:       Optional[dict] = None,
) -> list[dict]:
    """
    조건에 맞는 수신자만 반환.
    """
    if not recipients:
        return []

    if track == "reference":
        matched = [r for r in recipients if int(r.get("receive_reference", 0)) == 1]
        logger.info(f"  📨 [reference] 수신자 {len(matched)}/{len(recipients)}명")
        return matched

    # monitor 트랙
    classification = (tone or {}).get("classification", "미분석")

    if classification == "비우호":
        # 비우호 = 기존 tier1_warn 권한 (높은 우선순위 알림)
        matched = [r for r in recipients
                   if int(r.get("receive_tier1_warn", 1)) == 1]
        logger.info(f"  📨 [비우호] 수신자 {len(matched)}/{len(recipients)}명")
        return matched

    if classification == "일반":
        # 일반 = 기존 tier1_good 권한 (낮은 우선순위)
        matched = [r for r in recipients
                   if int(r.get("receive_tier1_good", 1)) == 1]
        logger.info(f"  📨 [일반] 수신자 {len(matched)}/{len(recipients)}명")
        return matched

    # 미분석은 기본적으로 발송하지 않음 (관리자가 별도로 확인)
    logger.info(f"  📨 [미분석] 발송 스킵")
    return []