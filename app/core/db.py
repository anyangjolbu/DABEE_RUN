# app/core/db.py
"""
SQLite 연결 관리.

- 단일 파일(articles.db) DB
- WAL 모드로 동시 읽기·쓰기 안전성 확보
- FastAPI 의존성으로 주입 가능한 컨텍스트 매니저 제공
"""

import sqlite3
import logging
from contextlib import contextmanager
from typing import Iterator

from app import config

logger = logging.getLogger(__name__)


def _connect() -> sqlite3.Connection:
    """
    새 연결을 생성하고 SQLite 권장 PRAGMA를 적용합니다.

    PRAGMA 설명:
    - journal_mode=WAL: 쓰기 중에도 읽기 가능. 동시성 핵심.
    - synchronous=NORMAL: WAL 모드에서 권장. FULL보다 빠르고 안전성 충분.
    - foreign_keys=ON: SQLite 기본값이 OFF라 명시적으로 켭니다.
    - busy_timeout: 다른 연결이 락을 잡고 있을 때 5초 대기 후 에러.
    """
    conn = sqlite3.connect(
        config.DB_PATH,
        check_same_thread=False,   # FastAPI 비동기 환경에서 필요
        timeout=10.0,
    )
    # 결과를 dict처럼 컬럼명으로 접근할 수 있게 해줍니다.
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """
    with 블록 안에서 안전하게 연결을 사용하기 위한 컨텍스트 매니저.

    사용 예:
        with get_conn() as conn:
            rows = conn.execute("SELECT * FROM articles").fetchall()

    - 정상 종료 시 자동 commit
    - 예외 발생 시 자동 rollback
    - 항상 close
    """
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """
    앱 시작 시 1회 호출. DB 파일과 테이블이 없으면 생성합니다.
    """
    from app.core import models   # 순환 참조 방지를 위해 함수 내 import

    logger.info(f"DB 초기화 시작 → {config.DB_PATH}")
    with get_conn() as conn:
        models.create_all(conn)
    logger.info("DB 초기화 완료")
