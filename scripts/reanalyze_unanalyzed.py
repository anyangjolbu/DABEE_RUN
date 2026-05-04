"""
미분석/LLM에러 monitor 레코드 일괄 재분석.
사용:
    python scripts/reanalyze_unanalyzed.py [limit]
"""
import sys
import os
import logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

from app.services.reanalyze import reanalyze_unanalyzed

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 100
result = reanalyze_unanalyzed(limit=LIMIT)
print()
print(f"대상 {result['target']}건 → "
      f"양호 {result['양호']} / 비우호 {result['비우호']} / "
      f"미분석 {result['미분석']} / 에러 {result['에러']}")
