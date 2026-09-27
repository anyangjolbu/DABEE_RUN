"""
DB CRUD 단일 진입점.

STEP 4A-1: article_save에 track, tone_classification, tone_reason,
tone_confidence 컬럼 반영. 기존 함수 시그니처 호환 유지.
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
# STEP-COST-2: 재분석이 필요 없는 확정 '미분석'(대상 미등장·LLM 관련없음)은
# reanalyze_attempts를 이 값으로 저장해 재분석 SELECT(< 3)에서 영구 제외한다.
REANALYZE_FINAL = 99


def article_exists(url: str) -> bool:
    if not url:
        return False
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM articles WHERE url = ? LIMIT 1", (url,)
        ).fetchone()
    return row is not None


def article_save(article: dict, summary: str, tone: Optional[dict],
                 theme_label: str, press: str,
                 track: str = "monitor") -> Optional[int]:
    """
    기사 1건 INSERT.

    STEP 4A-1: track, tone_classification, tone_reason, tone_confidence,
    image_url을 함께 저장.
    """
    url           = article.get("link") or article.get("originallink", "")
    original_url  = article.get("originallink", "")
    title         = article.get("title", "")

    import re
    title_clean = re.sub(r"<[^>]+>", "", title).strip()

    description  = article.get("description", "")
    theme_id     = article.get("theme_id", "")
    tier         = int(article.get("tier", 1))
    matched_kw   = ", ".join(article.get("matched_keywords", []))
    pub_date     = article.get("pub_date_iso", "")
    image_url    = article.get("image_url", "") or None
    collected_at = datetime.now(config.KST).isoformat()

    # 톤 정보 분해
    if tone and isinstance(tone, dict):
        tone_classification = tone.get("classification") or None
        tone_reason         = tone.get("reason") or None
        tone_confidence     = tone.get("confidence") or None
        tone_level          = tone.get("level") or None
        tone_hostile        = int(tone.get("hostile_count", 0) or 0)
        tone_total          = int(tone.get("total_count", 0) or 0)
        tone_sentences      = json.dumps(
            tone.get("hostile_sentences", []),
            ensure_ascii=False,
        )
        reanalyze_attempts  = REANALYZE_FINAL if tone.get("final") else 0
    else:
        tone_classification = None
        tone_reason         = None
        tone_confidence     = None
        tone_level          = None
        tone_hostile        = 0
        tone_total          = 0
        tone_sentences      = None
        reanalyze_attempts  = 0

    sql = """
        INSERT INTO articles (
            url, original_url, title, title_clean, press,
            description, summary,
            theme_id, theme_label, tier, matched_kw,
            track, tone_classification, tone_reason, tone_confidence,
            tone_level, tone_hostile, tone_total, tone_sentences,
            image_url, pub_date, collected_at, reanalyze_attempts
        ) VALUES (?,?,?,?,?, ?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?)
    """
    try:
        with get_conn() as conn:
            cur = conn.execute(sql, (
                url, original_url, title, title_clean, press,
                description, summary,
                theme_id, theme_label, tier, matched_kw,
                track, tone_classification, tone_reason, tone_confidence,
                tone_level, tone_hostile, tone_total, tone_sentences,
                image_url, pub_date, collected_at, reanalyze_attempts,
            ))
            return cur.lastrowid
    except Exception as e:
        if "UNIQUE" in str(e):
            logger.debug(f"중복 URL: {url}")
        else:
            logger.error(f"❌ 기사 저장 실패: {e}")
        return None


# sent_status: 0=발송 전(또는 저장 후 중단), 1=1명 이상 성공, 2=전원 실패,
#              3=매칭 수신자 없음 (STEP-COST-2, 재발송 대상에서 제외)
SENT_NO_RECIPIENTS = 3


def article_mark_sent(article_id: int, success: bool) -> None:
    article_set_sent_status(article_id, 1 if success else 2)


def article_set_sent_status(article_id: int, status: int) -> None:
    sent_at = datetime.now(config.KST).isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE articles SET sent_at = ?, sent_status = ? WHERE id = ?",
            (sent_at, status, article_id),
        )


def article_last_collected_at() -> Optional[str]:
    """가장 최근 저장 기사의 collected_at (KST ISO). 없으면 None."""
    with get_conn() as conn:
        row = conn.execute("SELECT MAX(collected_at) AS m FROM articles").fetchone()
    return row["m"] if row and row["m"] else None


def articles_pending_send(since_iso: str, until_iso: str, limit: int = 50,
                          max_fails: int = 5) -> list[dict]:
    """재발송 후보.

    - sent_status=0: 저장 후 발송 단계가 끝나지 않은 기사
    - 활성 수신자 중 실패 기록만 있고(성공 없음) 실패가 max_fails 미만인 (기사, 수신자) 쌍이 있는 기사
    이미 복구됐거나 포기한 쌍은 제외해, 처리할 게 없는 기사가 LIMIT 자리를 차지하지 않게 한다.
    """
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM articles a
            WHERE a.collected_at >= ? AND a.collected_at < ?
              AND (a.sent_status = 0
                   OR EXISTS (
                       SELECT 1 FROM send_log f
                       JOIN recipients rc ON rc.id = f.recipient_id AND rc.enabled = 1
                       WHERE f.article_id = a.id AND f.success = 0
                         AND NOT EXISTS (SELECT 1 FROM send_log s
                                         WHERE s.article_id = f.article_id
                                           AND s.recipient_id = f.recipient_id
                                           AND s.success = 1)
                         AND (SELECT COUNT(*) FROM send_log c
                              WHERE c.article_id = f.article_id
                                AND c.recipient_id = f.recipient_id
                                AND c.success = 0) < ?))
            ORDER BY a.id ASC
            LIMIT ?
        """, (since_iso, until_iso, max_fails, limit)).fetchall()
    return [dict(r) for r in rows]


def article_recent(limit: int = 50, offset: int = 0) -> list[dict]:
    sql = """
        SELECT * FROM articles
        ORDER BY COALESCE(pub_date, collected_at) DESC, id DESC
        LIMIT ? OFFSET ?
    """
    with get_conn() as conn:
        rows = conn.execute(sql, (limit, offset)).fetchall()
    return [dict(r) for r in rows]


def article_count() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]


def article_filter(
    limit:           int = 50,
    offset:          int = 0,
    tier:            Optional[int]  = None,
    theme:           Optional[str]  = None,
    search:          Optional[str]  = None,
    tone:            Optional[str]  = None,
    track:           Optional[str]  = None,
    classification:  Optional[str]  = None,
) -> tuple[list[dict], int]:
    """
    필터/검색 조합 기사 조회. (rows, total) 반환.

    STEP 4A-1:
    - track ('monitor' | 'reference') 필터 추가
    - classification ('비우호' | '일반' | '미분석') 필터 추가
    """
    where:  list[str] = []
    params: list      = []

    if tier is not None:
        where.append("tier = ?"); params.append(tier)
    if theme:
        where.append("theme_id = ?"); params.append(theme)
    if track:
        where.append("track = ?"); params.append(track)
    if classification:
        where.append("tone_classification = ?"); params.append(classification)
    if tone:  # 하위호환: tone_level
        where.append("tone_level = ?"); params.append(tone)
    if search:
        like = f"%{search}%"
        where.append("(title_clean LIKE ? OR summary LIKE ?)")
        params.extend([like, like])

    w = ("WHERE " + " AND ".join(where)) if where else ""
    # STEP-PERF-1: idx_articles_*sort 인덱스와 같은 순서. id DESC로 동점 순서 고정 (페이지 간 중복·누락 방지)
    order = "ORDER BY COALESCE(pub_date, collected_at) DESC, id DESC"

    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM articles {w}", params).fetchone()[0]
        rows  = conn.execute(
            f"SELECT * FROM articles {w} {order} LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
    return [dict(r) for r in rows], total


def article_daily(date_str: str, limit: int = 20) -> list[dict]:
    start = f"{date_str}T00:00:00"
    end   = f"{date_str}T23:59:59"
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM articles
               WHERE (pub_date >= ? AND pub_date <= ?)
                  OR (pub_date IS NULL AND collected_at >= ? AND collected_at <= ?)
               ORDER BY tier ASC, COALESCE(pub_date, collected_at) DESC
               LIMIT ?""",
            (start, end, start, end, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ════════════════════════════════════════════════════════════
#  Recipient
# ════════════════════════════════════════════════════════════

def article_window(start_iso: str, end_iso: str,
                   tracks: tuple = ("monitor", "reference")) -> list[dict]:
    """시간 윈도우 [start_iso, end_iso) 내 기사 조회.

    Args:
        start_iso: KST ISO 시각 (포함)
        end_iso:   KST ISO 시각 (제외)
        tracks:    트랙 필터. 기본 (monitor, reference) 둘 다.

    Returns:
        article dict 리스트. 시간 오름차순.
    """
    placeholders = ",".join("?" * len(tracks))
    sql = f"""
        SELECT * FROM articles
        WHERE collected_at >= ? AND collected_at < ?
          AND track IN ({placeholders})
        ORDER BY collected_at ASC
    """
    with get_conn() as conn:
        rows = conn.execute(sql, (start_iso, end_iso, *tracks)).fetchall()
    return [dict(r) for r in rows]

def recipient_list_active() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM recipients WHERE enabled = 1 ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def recipient_list_all() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM recipients ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def recipient_update(rid: int, **kwargs) -> bool:
    allowed = {
        "name", "role", "enabled",
        "receive_monitor",          # STEP-3B-27 신규 (monitor 트랙 수신)
        "receive_reference",        # reference 트랙 수신
        "receive_daily_report",     # 일간 리포트 수신
        # 레거시 컬럼 (무시되지만 PATCH 호환 위해 허용)
        "receive_tier1_warn", "receive_tier1_watch", "receive_tier1_good",
        "receive_tier2", "receive_tier3",
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
    perms = permissions or {}
    created_at = datetime.now(config.KST).isoformat()

    sql = """
        INSERT INTO recipients (
            chat_id, name, role,
            receive_monitor, receive_reference, receive_daily_report,
            receive_tier1_warn, receive_tier1_watch, receive_tier1_good,
            receive_tier2, receive_tier3,
            enabled, created_at
        ) VALUES (?,?,?, ?,?,?, ?,?,?, ?,?, 1, ?)
    """
    try:
        with get_conn() as conn:
            # STEP-3B-27: 신규 3종 권한만 운영. 레거시 컬럼은 monitor 값으로 함께 채움(롤백 안전).
            mon   = int(perms.get("receive_monitor",      1))
            ref   = int(perms.get("receive_reference",    1))
            daily = int(perms.get("receive_daily_report", 1))
            cur = conn.execute(sql, (
                chat_id, name, role,
                mon, ref, daily,
                mon, mon, mon,   # 레거시 tier1_warn/watch/good = monitor와 동일
                mon, 0,          # 레거시 tier2 = monitor, tier3 = 0
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
#  Daily Reports
# ════════════════════════════════════════════════════════════
def report_save(date_str: str, slot: str, body: str,
                payload_json: str, recipients_count: int) -> None:
    """슬롯별 리포트 저장. slot in ('morning', 'evening')."""
    sent_at = datetime.now(config.KST).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO daily_reports
               (report_date, slot, sent_at, body, payload_json, recipients_count)
               VALUES (?,?,?,?,?,?)""",
            (date_str, slot, sent_at, body, payload_json, recipients_count),
        )


def report_list(limit: int = 30) -> list[dict]:
    """최근 리포트 목록 (슬롯 포함)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT report_date, slot, sent_at, recipients_count"
            " FROM daily_reports ORDER BY sent_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def report_get(date_str: str, slot: str = "evening") -> Optional[dict]:
    """슬롯별 리포트 조회."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM daily_reports WHERE report_date = ? AND slot = ?",
            (date_str, slot),
        ).fetchone()
    return dict(row) if row else None


def report_delete(date_str: str, slot: str) -> int:
    """슬롯별 리포트 행 삭제. 강제 재생성 시 사용. 삭제된 row 수 반환."""
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM daily_reports WHERE report_date = ? AND slot = ?",
            (date_str, slot),
        )
        return cur.rowcount


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
def sendlog_status(article_id: int) -> tuple[set, dict]:
    """(성공한 recipient_id 집합, recipient_id별 실패 횟수)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT recipient_id, success FROM send_log WHERE article_id = ?",
            (article_id,),
        ).fetchall()
    ok: set = set()
    fails: dict = {}
    for r in rows:
        if r["success"]:
            ok.add(r["recipient_id"])
        else:
            fails[r["recipient_id"]] = fails.get(r["recipient_id"], 0) + 1
    return ok, fails


def sendlog_record(article_id: int, recipient_id: int,
                   success: bool, error_msg: str = "") -> None:
    sent_at = datetime.now(config.KST).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO send_log
               (article_id, recipient_id, sent_at, success, error_msg)
               VALUES (?,?,?,?,?)""",
            (article_id, recipient_id, sent_at, 1 if success else 0, error_msg),
        )
