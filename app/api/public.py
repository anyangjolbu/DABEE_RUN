# app/api/public.py
"""
공개 API 라우터. 인증 불필요.

엔드포인트:
    GET /api/health          : 헬스체크
    GET /api/articles        : 기사 목록 (필터·검색·페이지네이션)
    GET /api/themes          : 검색 테마 목록 (피드 필터용)
    GET /api/scheduler       : 스케줄러 상태
    GET /api/reports         : 일간 리포트 목록
    GET /api/reports/{date}  : 특정 날짜 리포트 내용
"""

from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.core import repository
from app.core.db import get_conn
from app.core.scheduler import scheduler
from app.services.settings_store import load_settings

router = APIRouter()


@router.get("/health")
async def health():
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
    limit:  int           = Query(50, ge=1, le=200),
    offset: int           = Query(0,  ge=0),
    tier:   Optional[int] = Query(None),
    theme:  Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    tone:   Optional[str] = Query(None),
):
    """기사 목록. tier/theme/search/tone 파라미터로 필터 가능."""
    has_filter = any(v is not None for v in [tier, theme, search, tone])

    if has_filter:
        items, total = repository.article_filter(
            limit=limit, offset=offset,
            tier=tier, theme=theme, search=search, tone=tone,
        )
    else:
        items = repository.article_recent(limit=limit, offset=offset)
        total = repository.article_count()

    return JSONResponse({"total": total, "limit": limit, "offset": offset, "items": items})


@router.get("/themes")
async def list_themes():
    """검색 테마 목록 (공개용 — 라벨·티어만, 키워드 제외)."""
    themes = load_settings().get("search_themes", {})
    result = [
        {"id": tid, "label": t.get("label", tid), "tier": t.get("tier", 3)}
        for tid, t in themes.items()
    ]
    return sorted(result, key=lambda x: (x["tier"], x["label"]))


@router.get("/scheduler")
async def scheduler_status():
    return JSONResponse(scheduler.status())


@router.get("/reports")
async def list_reports(limit: int = Query(30, ge=1, le=100)):
    """일간 리포트 목록 (날짜 역순)."""
    return repository.report_list(limit=limit)


@router.get("/reports/{date}")
async def get_report(date: str):
    """특정 날짜 리포트. date='today'면 오늘 날짜로 처리."""
    from datetime import datetime
    from app import config
    if date == "today":
        date = datetime.now(config.KST).strftime("%Y-%m-%d")
    report = repository.report_get(date)
    if not report:
        return JSONResponse({"error": "리포트 없음"}, status_code=404)
    return report
