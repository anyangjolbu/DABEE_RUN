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

import secrets
from datetime import datetime, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app import config
from app.core import repository as repo
from app.core.scheduler import scheduler
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
