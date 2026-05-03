# app/core/repository.py
"""
DB CRUD 단일 진입점.

서비스 레이어가 SQL을 직접 쓰지 않도록 모든 DB 접근을 이 모듈로
통과시킵니다. 함수 단위로 분리해 테스트와 재사용이 쉽도록 했습니다.

함수 명명 규칙:
    - article_*  : articles 테이블 관련
    - recipient_*: recipients 테이블 관련
    - sendlog_*  : send_log 테이블 관련
"""

import json
import logging
from datetime import datetime
from typing import Optional

from app import config
from app.core.db import get_conn

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
#  Article
# ════════════════════════════════════════════════════════════
def article_exists(url: str) -> bool:
    """URL이 이미 articles 테이블에 있으면 True. 중복 체크용."""
    if not url:
        return False
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM articles WHERE url = ? LIMIT 1", (url,)
        ).fetchone()
    return row is not None


def article_save(article: dict, summary: str, tone: Optional[dict],
                 theme_label: str, press: str) -> Optional[int]:
    """
    기사 1건을 articles 테이블에 INSERT.

    Args:
        article: 파이프라인이 다룬 기사 dict
        summary: 요약 결과
        tone:    analyze_tone() 결과 dict 또는 None (TIER 2/3)
        theme_label: 테마 라벨 (이모지 포함)
        press: 매체명

    Returns:
        새로 생성된 row id. URL 중복 등으로 실패 시 None.
    """
    url           = article.get("link") or article.get("originallink", "")
    original_url  = article.get("originallink", "")
    title         = article.get("title", "")

    # title_clean: HTML 태그 제거한 검색용 제목
    import re
    title_clean = re.sub(r"<[^>]+>", "", title).strip()

    description = article.get("description", "")
    theme_id    = article.get("theme_id", "")
    tier        = int(article.get("tier", 3))
    matched_kw  = ", ".join(article.get("matched_keywords", []))
    pub_date    = article.get("pub_date_iso", "")
    collected_at = datetime.now(config.KST).isoformat()

    # 톤 정보 분해
    if tone and isinstance(tone, dict):
        tone_level     = tone.get("level")
        tone_hostile   = int(tone.get("hostile_count", 0))
        tone_total     = int(tone.get("total_count", 0))
        tone_sentences = json.dumps(
            tone.get("hostile_sentences", []),
            ensure_ascii=False,
        )
    else:
        tone_level     = None
        tone_hostile   = 0
        tone_total     = 0
        tone_sentences = None

    sql = """
        INSERT INTO articles (
            url, original_url, title, title_clean, press,
            description, summary,
            theme_id, theme_label, tier, matched_kw,
            tone_level, tone_hostile, tone_total, tone_sentences,
            pub_date, collected_at
        ) VALUES (?,?,?,?,?, ?,?, ?,?,?,?, ?,?,?,?, ?,?)
    """
    try:
        with get_conn() as conn:
            cur = conn.execute(sql, (
                url, original_url, title, title_clean, press,
                description, summary,
                theme_id, theme_label, tier, matched_kw,
                tone_level, tone_hostile, tone_total, tone_sentences,
                pub_date, collected_at,
            ))
            return cur.lastrowid
    except Exception as e:
        # URL UNIQUE 제약 위반은 정상적인 중복 → 경고로 끝
        if "UNIQUE" in str(e):
            logger.debug(f"중복 URL (이미 저장됨): {url}")
        else:
            logger.error(f"❌ 기사 저장 실패: {e}")
        return None


def article_mark_sent(article_id: int, success: bool) -> None:
    """텔레그램 발송 완료 시 articles.sent_at, sent_status 갱신."""
    sent_at = datetime.now(config.KST).isoformat()
    status  = 1 if success else 2
    with get_conn() as conn:
        conn.execute(
            "UPDATE articles SET sent_at = ?, sent_status = ? WHERE id = ?",
            (sent_at, status, article_id),
        )


def article_recent(limit: int = 50, offset: int = 0) -> list[dict]:
    """최근 기사 조회 (pub_date 또는 collected_at 역순)."""
    sql = """
        SELECT * FROM articles
        ORDER BY COALESCE(pub_date, collected_at) DESC
        LIMIT ? OFFSET ?
    """
    with get_conn() as conn:
        rows = conn.execute(sql, (limit, offset)).fetchall()
    return [dict(r) for r in rows]


def article_count() -> int:
    """전체 기사 수."""
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]


# ════════════════════════════════════════════════════════════
#  Recipient
# ════════════════════════════════════════════════════════════
def recipient_list_active() -> list[dict]:
    """발송 활성화된 수신자 전체."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM recipients WHERE enabled = 1 ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def recipient_list_all() -> list[dict]:
    """관리자용: 비활성 포함 전체 수신자 목록."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM recipients ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def recipient_update(rid: int, **kwargs) -> bool:
    allowed = {
        "name", "role", "enabled",
        "receive_tier1_warn", "receive_tier1_watch", "receive_tier1_good",
        "receive_tier2", "receive_tier3", "receive_daily_report",
    }
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [rid]
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE recipients SET {set_clause} WHERE id = ?", values
        )
    return cur.rowcount > 0


def recipient_delete(rid: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM recipients WHERE id = ?", (rid,))
    return cur.rowcount > 0


def recipient_add(chat_id: str, name: str, role: str = "",
                  permissions: Optional[dict] = None) -> Optional[int]:
    """
    수신자 추가.

    permissions 예:
        {
            "receive_tier1_warn":  1,
            "receive_tier1_watch": 1,
            "receive_tier1_good":  1,
            "receive_tier2":       1,
            "receive_tier3":       0,
            "receive_daily_report": 1,
        }
    """
    perms = permissions or {}
    created_at = datetime.now(config.KST).isoformat()

    sql = """
        INSERT INTO recipients (
            chat_id, name, role,
            receive_tier1_warn, receive_tier1_watch, receive_tier1_good,
            receive_tier2, receive_tier3, receive_daily_report,
            enabled, created_at
        ) VALUES (?,?,?, ?,?,?, ?,?,?, 1, ?)
    """
    try:
        with get_conn() as conn:
            cur = conn.execute(sql, (
                chat_id, name, role,
                perms.get("receive_tier1_warn",   1),
                perms.get("receive_tier1_watch",  1),
                perms.get("receive_tier1_good",   1),
                perms.get("receive_tier2",        1),
                perms.get("receive_tier3",        0),
                perms.get("receive_daily_report", 1),
                created_at,
            ))
            return cur.lastrowid
    except Exception as e:
        if "UNIQUE" in str(e):
            logger.warning(f"수신자 chat_id 중복: {chat_id}")
        else:
            logger.error(f"❌ 수신자 추가 실패: {e}")
        return None


# ════════════════════════════════════════════════════════════
#  Admin Sessions
# ════════════════════════════════════════════════════════════
def session_create(token: str, user_agent: str, expires_at: str) -> None:
    created_at = datetime.now(config.KST).isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO admin_sessions (token, created_at, expires_at, user_agent)"
            " VALUES (?,?,?,?)",
            (token, created_at, expires_at, user_agent),
        )


def session_get(token: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM admin_sessions WHERE token = ?", (token,)
        ).fetchone()
    return dict(row) if row else None


def session_delete(token: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))


def session_cleanup() -> None:
    now = datetime.now(config.KST).isoformat()
    with get_conn() as conn:
        conn.execute("DELETE FROM admin_sessions WHERE expires_at < ?", (now,))


# ════════════════════════════════════════════════════════════
#  SendLog
# ════════════════════════════════════════════════════════════
def sendlog_record(article_id: int, recipient_id: int,
                   success: bool, error_msg: str = "") -> None:
    """발송 결과 1건을 send_log에 기록."""
    sent_at = datetime.now(config.KST).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO send_log
               (article_id, recipient_id, sent_at, success, error_msg)
               VALUES (?,?,?,?,?)""",
            (article_id, recipient_id, sent_at, 1 if success else 0, error_msg),
        )
