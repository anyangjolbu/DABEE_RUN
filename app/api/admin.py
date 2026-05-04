# app/api/admin.py
"""
관리자 API 라우터.

인증: ADMIN_PASSWORD 단일 비밀번호 → admin_sessions 토큰 → HttpOnly 쿠키 7일 유지.
모든 /api/admin/* 엔드포인트는 require_admin dependency가 보호.

엔드포인트:
    POST /api/admin/login              : 로그인
    POST /api/admin/logout             : 로그아웃
    GET  /api/admin/settings           : 현재 설정 조회
    PATCH /api/admin/settings          : 설정 일부 수정
    GET  /api/admin/recipients         : 수신자 전체 목록
    POST /api/admin/recipients         : 수신자 추가
    PATCH /api/admin/recipients/{rid}  : 수신자 수정
    DELETE /api/admin/recipients/{rid} : 수신자 삭제
    POST /api/admin/scheduler/trigger  : 파이프라인 즉시 실행
    POST /api/admin/scheduler/start    : 스케줄러 시작
    POST /api/admin/scheduler/stop     : 스케줄러 정지
"""

import os
import re
import secrets
from datetime import datetime, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from app import config
from app.core import repository as repo
from app.core.scheduler import scheduler
from app.core.ws_manager import WSLogHandler
from app.services.settings_store import load_settings, save_settings

router = APIRouter()

_COOKIE   = "dabee_admin"
_TTL_DAYS = 7


# ── 인증 헬퍼 ────────────────────────────────────────────────

def _make_session(user_agent: str) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = (
        datetime.now(config.KST) + timedelta(days=_TTL_DAYS)
    ).isoformat()
    repo.session_create(token, user_agent, expires_at)
    repo.session_cleanup()
    return token


def get_session(request: Request) -> Optional[dict]:
    """쿠키 검증 후 유효한 세션 dict 반환. 없거나 만료면 None."""
    token = request.cookies.get(_COOKIE)
    if not token:
        return None
    session = repo.session_get(token)
    if not session:
        return None
    if session["expires_at"] < datetime.now(config.KST).isoformat():
        repo.session_delete(token)
        return None
    return session


async def require_admin(request: Request) -> str:
    """FastAPI Dependency. 미인증 시 HTTP 401."""
    session = get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="인증 필요")
    return session["token"]


AdminDep = Annotated[str, Depends(require_admin)]


# ── 로그인 / 로그아웃 ────────────────────────────────────────

@router.post("/login")
async def login(request: Request, response: Response):
    body = await request.json()
    password = body.get("password", "")

    if not config.ADMIN_PASSWORD:
        raise HTTPException(status_code=503, detail="ADMIN_PASSWORD 미설정")

    if not secrets.compare_digest(
        password.encode(), config.ADMIN_PASSWORD.encode()
    ):
        raise HTTPException(status_code=401, detail="비밀번호 오류")

    token = _make_session(request.headers.get("user-agent", ""))
    response.set_cookie(
        _COOKIE, token,
        httponly=True,
        samesite="lax",
        max_age=_TTL_DAYS * 86400,
    )
    return {"ok": True}


@router.post("/logout")
async def logout(token: AdminDep, response: Response):
    repo.session_delete(token)
    response.delete_cookie(_COOKIE)
    return {"ok": True}


# ── 설정 ─────────────────────────────────────────────────────

@router.get("/settings")
async def get_settings(_: AdminDep):
    return load_settings()


@router.patch("/settings")
async def patch_settings(request: Request, _: AdminDep):
    body = await request.json()
    s = load_settings()
    s.update(body)
    save_settings(s)
    return s


# ── 수신자 CRUD ───────────────────────────────────────────────

@router.get("/recipients")
async def list_recipients(_: AdminDep):
    return repo.recipient_list_all()


@router.post("/recipients")
async def add_recipient(request: Request, _: AdminDep):
    body = await request.json()
    rid = repo.recipient_add(
        str(body["chat_id"]),
        body["name"],
        body.get("role", ""),
        body.get("permissions"),
    )
    if rid is None:
        raise HTTPException(status_code=409, detail="chat_id 중복")
    return {"id": rid}


@router.patch("/recipients/{rid}")
async def update_recipient(rid: int, request: Request, _: AdminDep):
    body = await request.json()
    ok = repo.recipient_update(rid, **body)
    if not ok:
        raise HTTPException(status_code=404, detail="수신자 없음")
    return {"ok": True}


@router.delete("/recipients/{rid}")
async def delete_recipient(rid: int, _: AdminDep):
    ok = repo.recipient_delete(rid)
    if not ok:
        raise HTTPException(status_code=404, detail="수신자 없음")
    return {"ok": True}


# ── 스케줄러 제어 ─────────────────────────────────────────────

@router.post("/scheduler/trigger")
async def trigger_pipeline(_: AdminDep):
    await scheduler.trigger_now()
    return {"status": "triggered"}


@router.post("/scheduler/start")
async def start_scheduler(_: AdminDep):
    await scheduler.start()
    return {"status": "started"}


@router.post("/scheduler/stop")
async def stop_scheduler(_: AdminDep):
    await scheduler.stop()
    return {"status": "stopped"}

# ── DB 관리 (STEP 3B-1) ──────────────────────────────────────

@router.post("/db/reset")
async def db_reset(request: Request, _: AdminDep):
    """
    articles + send_log 전체 삭제. 
    settings/recipients/admin_sessions/themes는 보존.
    body: {"confirm": "RESET"}  — 안전장치
    """
    body = await request.json()
    if body.get("confirm") != "RESET":
        raise HTTPException(status_code=400, detail='confirm="RESET" 필요')

    from app.core.db import get_conn
    with get_conn() as conn:
        before = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        conn.execute("DELETE FROM send_log")
        conn.execute("DELETE FROM articles")
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('articles','send_log')")
        conn.commit()
    return {"ok": True, "deleted": before}


@router.get("/db/stats")
async def db_stats(_: AdminDep):
    """대시보드용 빠른 통계."""
    from app.core.db import get_conn
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        rows  = conn.execute("""
            SELECT track, tone_classification, COUNT(*) as n
            FROM articles GROUP BY track, tone_classification
        """).fetchall()
    dist = [{"track": r["track"], "classification": r["tone_classification"], "n": r["n"]} for r in rows]
    return {"total": total, "distribution": dist}


# ── 라이브 로그 — 과거분 tail (STEP-3B-15) ─────────────────────

# monitor.log 라인 파서: "2026-05-04 00:27:13 [INFO] app.services.pipeline — 메시지"
_LOG_LINE_RE = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
    r"\[(?P<level>[A-Z]+)\]\s+"
    r"(?P<logger>[^—-]+?)\s+[—-]\s+"
    r"(?P<message>.*)$"
)


def _tail_log_file(path: str, n_lines: int, max_bytes: int = 512 * 1024) -> list[str]:
    """파일 끝에서 최대 n_lines줄 효율적으로 읽기.

    한 줄 평균 길이를 가정해 max_bytes만큼만 읽고 마지막 N줄을 자릅니다.
    1.8MB 파일에서 300줄 추출은 수백 ms 이내.
    """
    if not os.path.exists(path):
        return []
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size == 0:
                return []
            read_size = min(size, max(max_bytes, n_lines * 400))
            f.seek(size - read_size)
            data = f.read()
    except Exception:
        return []

    text = data.decode("utf-8", errors="replace")
    if size > read_size:
        # 잘렸을 수 있는 첫 줄 버림
        nl = text.find("\n")
        if nl >= 0:
            text = text[nl + 1:]
    raw_lines = [ln for ln in text.split("\n") if ln.strip()]
    return raw_lines[-n_lines:]


def _is_blacklisted(logger_name: str) -> bool:
    """WS 로그 핸들러와 동일한 노이즈 필터를 과거 로그에도 적용."""
    for blocked in WSLogHandler.WS_LOG_BLACKLIST:
        if logger_name.startswith(blocked):
            return True
    return False


@router.get("/logs")
async def get_logs(
    _: AdminDep,
    limit:    int  = Query(300, ge=10, le=2000),
    raw:      bool = Query(False, description="True면 파싱 없이 원문 반환"),
    no_filter:bool = Query(False, description="True면 노이즈 블랙리스트 무시"),
):
    """monitor.log 끝에서 N줄을 파싱해 반환. WS 라이브 로그의 과거분."""
    raw_lines = _tail_log_file(str(config.LOG_PATH), limit * 2)  # 필터로 줄어들 여유

    parsed: list[dict] = []
    for ln in raw_lines:
        m = _LOG_LINE_RE.match(ln)
        if not m:
            # 멀티라인 메시지의 후속 줄 — 직전 메시지에 이어붙임
            if parsed:
                parsed[-1]["message"] += "\n" + ln
            continue
        logger_name = m.group("logger").strip()
        if not no_filter and _is_blacklisted(logger_name):
            continue
        parsed.append({
            "time":    m.group("time"),
            "level":   m.group("level"),
            "logger":  logger_name,
            "message": m.group("message"),
        })

    parsed = parsed[-limit:]
    if raw:
        return JSONResponse({"lines": raw_lines[-limit:]})
    return JSONResponse({"lines": parsed})
