"""
수신자 매칭.

STEP-3B-20 변경:
- monitor 트랙이면 분류(비우호/양호/미분석/LLM에러) 무관하게 monitor 권한자 전원에게 발송.
  PR팀이 모니터링 대상 기사를 빠짐없이 보게 하기 위함.
- reference 트랙은 기존대로 receive_reference=1인 수신자만.

수신자 권한 키:
- receive_tier1_warn  : monitor 트랙 발송 권한 (이름은 레거시, 실제로는 monitor 전체)
- receive_reference   : reference 트랙 발송 권한
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

    monitor   → receive_tier1_warn=1 인 모든 수신자 (분류 무관)
    reference → receive_reference=1  인 모든 수신자
    """
    if not recipients:
        return []

    if track == "reference":
        matched = [r for r in recipients if int(r.get("receive_reference", 0)) == 1]
        logger.info(f"  📨 [reference] 수신자 {len(matched)}/{len(recipients)}명")
        return matched

    # monitor 트랙 — 분류 무관 전원 발송
    classification = (tone or {}).get("classification", "미분석")
    matched = [r for r in recipients
               if int(r.get("receive_tier1_warn", 1)) == 1]
    logger.info(
        f"  📨 [monitor/{classification}] 수신자 {len(matched)}/{len(recipients)}명"
    )
    return matched
