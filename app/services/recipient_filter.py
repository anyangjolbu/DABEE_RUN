"""
수신자 매칭.

STEP-3B-27 변경:
- 권한 모델 단순화. receive_monitor / receive_reference / receive_daily_report 3종만 운영.
- monitor 트랙이면 receive_monitor=1 인 수신자 전원에게 발송 (분류 무관).
- reference 트랙이면 receive_reference=1 인 수신자 전원에게 발송.
- 레거시 컬럼(receive_tier1_warn 등)은 더 이상 참조하지 않음.
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

    monitor   → receive_monitor=1   인 수신자 (분류 무관)
    reference → receive_reference=1 인 수신자
    """
    if not recipients:
        return []

    if track == "reference":
        matched = [r for r in recipients if int(r.get("receive_reference", 0)) == 1]
        logger.info(f"  📨 [reference] 수신자 {len(matched)}/{len(recipients)}명")
        return matched

    # monitor 트랙 — 분류 무관 전원 발송
    classification = (tone or {}).get("classification", "미분석")
    matched = [
        r for r in recipients
        if int(r.get("receive_monitor", r.get("receive_tier1_warn", 1))) == 1
    ]
    logger.info(
        f"  📨 [monitor/{classification}] 수신자 {len(matched)}/{len(recipients)}명"
    )
    return matched
