# scripts/test_pipeline.py
"""
파이프라인 통합 실행 (STEP 2C).

기본은 dry_run=True로 안전 모드.
실제 DB 저장 + 텔레그램 발송을 하려면 인자에 'real' 전달.

사용법:
    python -m scripts.test_pipeline           # dry_run, 1건만
    python -m scripts.test_pipeline real      # 실제 발송, 3건
    python -m scripts.test_pipeline real 10   # 실제 발송, 10건
"""

import sys

from app.core.logging_setup import setup_logging
from app.core import db
from app.services import pipeline


def main():
    setup_logging()
    db.init_db()

    args = sys.argv[1:]
    real = "real" in args

    # max 개수 결정
    max_articles = None
    for a in args:
        if a.isdigit():
            max_articles = int(a)
            break
    if max_articles is None:
        max_articles = 3 if real else 1

    print(f"🧪 모드: {'REAL (DB+텔레그램)' if real else 'DRY_RUN'}")
    print(f"🔢 최대 기사 수: {max_articles}")
    print()

    result = pipeline.run_once(dry_run=not real, max_articles=max_articles)

    print()
    print("=" * 60)
    print("최종 결과:")
    for k, v in result.items():
        print(f"  {k:15s}: {v}")


if __name__ == "__main__":
    main()
