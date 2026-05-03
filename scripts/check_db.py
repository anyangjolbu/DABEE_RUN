# scripts/check_db.py
"""
DB 상태 확인용 스크립트.

사용법:
    python -m scripts.check_db
"""

import sqlite3
from app import config


def main():
    print(f"DB 경로: {config.DB_PATH}")
    print(f"파일 존재: {config.DB_PATH.exists()}")
    print()

    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row

    # 테이블 목록
    tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    print(f"테이블 ({len(tables)}개):")
    for t in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  - {t:20s} ({count}건)")

    # WAL 모드 확인
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    print(f"\njournal_mode: {mode}")

    conn.close()


if __name__ == "__main__":
    main()
