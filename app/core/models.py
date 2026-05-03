"""
DB 테이블 스키마 정의.

create_all()을 호출하면 존재하지 않는 테이블·인덱스·컬럼만 생성합니다.
멱등성을 보장하므로 서버 재시작에 안전합니다.

STEP 4A-1: track, tone_classification, tone_reason, tone_confidence,
image_url, receive_reference 컬럼을 ALTER로 추가합니다.
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)


SCHEMA = [
    # ─── 기사 본체 ─────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS articles (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        url             TEXT    UNIQUE NOT NULL,
        original_url    TEXT,
        title           TEXT    NOT NULL,
        title_clean     TEXT,
        press           TEXT,
        description     TEXT,
        summary         TEXT,

        theme_id        TEXT    NOT NULL,
        theme_label     TEXT,
        tier            INTEGER,
        matched_kw      TEXT,

        tone_level      TEXT,
        tone_hostile    INTEGER DEFAULT 0,
        tone_total      INTEGER DEFAULT 0,
        tone_sentences  TEXT,

        pub_date        TEXT,
        collected_at    TEXT    NOT NULL,
        sent_at         TEXT,
        sent_status     INTEGER DEFAULT 0
    )
    """,

    "CREATE INDEX IF NOT EXISTS idx_articles_collected   ON articles(collected_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_articles_pub         ON articles(pub_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_articles_theme_date  ON articles(theme_id, collected_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_articles_tier_tone   ON articles(tier, tone_level, collected_at DESC)",

    # ─── 텔레그램 수신자 ────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS recipients (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id               TEXT    UNIQUE NOT NULL,
        name                  TEXT    NOT NULL,
        role                  TEXT,

        receive_tier1_warn    INTEGER DEFAULT 1,
        receive_tier1_watch   INTEGER DEFAULT 1,
        receive_tier1_good    INTEGER DEFAULT 1,
        receive_tier2         INTEGER DEFAULT 1,
        receive_tier3         INTEGER DEFAULT 0,
        receive_daily_report  INTEGER DEFAULT 1,

        enabled               INTEGER DEFAULT 1,
        created_at            TEXT    NOT NULL
    )
    """,

    # ─── 관리자 세션 ────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS admin_sessions (
        token       TEXT    PRIMARY KEY,
        created_at  TEXT    NOT NULL,
        expires_at  TEXT    NOT NULL,
        user_agent  TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON admin_sessions(expires_at)",

    # ─── 발송 감사 로그 ─────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS send_log (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id    INTEGER NOT NULL,
        recipient_id  INTEGER NOT NULL,
        sent_at       TEXT    NOT NULL,
        success       INTEGER NOT NULL,
        error_msg     TEXT,
        FOREIGN KEY (article_id)   REFERENCES articles(id),
        FOREIGN KEY (recipient_id) REFERENCES recipients(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sendlog_article ON send_log(article_id)",

    # ─── 일간 리포트 발송 기록 ──────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS daily_reports (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        report_date       TEXT    UNIQUE NOT NULL,
        sent_at           TEXT    NOT NULL,
        body              TEXT,
        recipients_count  INTEGER
    )
    """,
]


# ─── ALTER 마이그레이션 (STEP 4A-1) ─────────────────────────────
#  멱등 처리: 컬럼이 없을 때만 ADD.
ALTER_MIGRATIONS = [
    ("articles",   "track",                "TEXT DEFAULT 'monitor'"),
    ("articles",   "tone_classification",  "TEXT"),
    ("articles",   "tone_reason",          "TEXT"),
    ("articles",   "tone_confidence",      "TEXT"),
    ("articles",   "image_url",            "TEXT"),
    ("recipients", "receive_reference",    "INTEGER DEFAULT 0"),
]

POST_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_articles_track_date     ON articles(track, collected_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_articles_classification ON articles(tone_classification, collected_at DESC)",
]


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def create_all(conn: sqlite3.Connection) -> None:
    """모든 테이블·인덱스·신규 컬럼을 생성합니다 (이미 존재하면 무시)."""
    for stmt in SCHEMA:
        conn.execute(stmt)

    # ALTER 마이그레이션
    for table, column, coldef in ALTER_MIGRATIONS:
        if not _column_exists(conn, table, column):
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coldef}")
                logger.info(f"  🔧 ALTER: {table}.{column} 추가")
            except Exception as e:
                logger.warning(f"  ⚠️ ALTER 실패 {table}.{column}: {e}")

    for stmt in POST_INDEXES:
        conn.execute(stmt)