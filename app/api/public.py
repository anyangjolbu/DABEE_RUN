# app/api/public.py
"""
공개 API 라우터. 인증 불필요.

엔드포인트:
    GET /api/health        : 시스템 상태
    GET /api/articles      : 기사 목록 (페이지네이션)
    GET /api/scheduler     : 스케줄러 현재 상태
"""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.core import repository
from app.core.db import get_conn
from app.core.scheduler import scheduler

router = APIRouter()


@router.get("/health")
async def health():
    """헬스체크 + DB 동작 확인."""
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1").fetchone()
        return JSONResponse({
            "status":    "ok",
            "db":        "ok",
            "scheduler": scheduler.status()["phase"],
        })
    except Exception as e:
        return JSONResponse(
            {"status": "error", "db": "fail", "error": str(e)},
            status_code=503,
        )


@router.get("/articles")
async def list_articles(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """최근 기사 목록."""
    items = repository.article_recent(limit=limit, offset=offset)
    total = repository.article_count()
    return JSONResponse({
        "total":  total,
        "limit":  limit,
        "offset": offset,
        "items":  items,
    })


@router.get("/scheduler")
async def scheduler_status():
    """스케줄러 현재 상태."""
    return JSONResponse(scheduler.status())
