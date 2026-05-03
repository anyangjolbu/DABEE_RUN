# scripts/seed_recipient.py
"""
테스트용 수신자 1명을 recipients 테이블에 추가.

사용법:
    python -m scripts.seed_recipient <chat_id> [name]

예:
    python -m scripts.seed_recipient 7996575375 "테스트 사용자"

이미 등록된 chat_id면 추가하지 않고 안내만 출력.
"""

import sys

from app.core.logging_setup import setup_logging
from app.core import repository, db


def main():
    setup_logging()
    db.init_db()

    if len(sys.argv) < 2:
        print("사용법: python -m scripts.seed_recipient <chat_id> [name]")
        sys.exit(1)

    chat_id = sys.argv[1]
    name    = sys.argv[2] if len(sys.argv) > 2 else "테스트 수신자"

    rid = repository.recipient_add(
        chat_id=chat_id,
        name=name,
        role="테스트",
        permissions={
            "receive_tier1_warn":   1,
            "receive_tier1_watch":  1,
            "receive_tier1_good":   1,
            "receive_tier2":        1,
            "receive_tier3":        1,
            "receive_daily_report": 1,
        },
    )
    if rid:
        print(f"✅ 수신자 추가 완료 (id={rid}, chat_id={chat_id}, name={name})")
    else:
        print(f"ℹ️ 추가 실패 또는 이미 존재 (chat_id={chat_id})")

    # 현재 등록된 수신자 출력
    print("\n현재 활성 수신자:")
    for r in repository.recipient_list_active():
        print(f"  - id={r['id']:3d} | {r['chat_id']:15s} | {r['name']}")


if __name__ == "__main__":
    main()
