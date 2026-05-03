# app/core/models.py
"""
DB 테이블 스키마 정의.

create_all()을 호출하면 존재하지 않는 테이블·인덱스만 생성합니다.
기존 테이블은 건드리지 않으므로 서버 재시작에 안전합니다.

스키마 변경이 필요한 경우 별도의 마이그레이션 스크립트
(scripts/migrate_*.py)로 처리합니다.
"""

import sqlite3


SCHEMA = [
    # ─── 기사 본체 ──────────────────────────────────────────────────
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

        tone_level      TEXT,                 -- 양호 | 주의 | 경고 | NULL
        tone_hostile    INTEGER DEFAULT 0,
        tone_total      INTEGER DEFAULT 0,
        tone_sentences  TEXT,                 -- JSON 배열 직렬화

        pub_date        TEXT,                 -- ISO8601 KST
        collected_at    TEXT    NOT NULL,     -- ISO8601 KST
        sent_at         TEXT,
        sent_status     INTEGER DEFAULT 0     -- 0=미발송 1=성공 2=실패
    )
    """,

    # 인덱스 — 자주 쓰는 정렬·필터 조합에 맞춰 설계
    "CREATE INDEX IF NOT EXISTS idx_articles_collected   ON articles(collected_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_articles_pub         ON articles(pub_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_articles_theme_date  ON articles(theme_id, collected_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_articles_tier_tone   ON articles(tier, tone_level, collected_at DESC)",

    # ─── 텔레그램 수신자 ────────────────────────────────────────────
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

    # ─── 관리자 세션 ────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS admin_sessions (
        token       TEXT    PRIMARY KEY,
        created_at  TEXT    NOT NULL,
        expires_at  TEXT    NOT NULL,
        user_agent  TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON admin_sessions(expires_at)",

    # ─── 발송 감사 로그 ─────────────────────────────────────────────
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

    # ─── 일간 리포트 발송 기록 ──────────────────────────────────────
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


def create_all(conn: sqlite3.Connection) -> None:
    """모든 테이블·인덱스를 생성합니다 (이미 존재하면 무시)."""
    for stmt in SCHEMA:
        conn.execute(stmt)
