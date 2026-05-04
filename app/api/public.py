# app/api/public.py
"""
공개 API 라우터. 인증 불필요.
"""

from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.core import repository, sentiment
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
    limit:          int           = Query(50, ge=1, le=200),
    offset:         int           = Query(0,  ge=0),
    tier:           Optional[int] = Query(None),
    theme:          Optional[str] = Query(None),
    search:         Optional[str] = Query(None),
    tone:           Optional[str] = Query(None),
    classification: Optional[str] = Query(None),
    track:          Optional[str] = Query(None),
):
    """기사 목록. tier/theme/search/tone/classification/track 필터."""
    has_filter = any(v is not None for v in
                     [tier, theme, search, tone, classification, track])

    if has_filter:
        items, total = repository.article_filter(
            limit=limit, offset=offset,
            tier=tier, theme=theme, search=search, tone=tone,
            classification=classification, track=track,
        )
    else:
        items = repository.article_recent(limit=limit, offset=offset)
        total = repository.article_count()

    return JSONResponse({"total": total, "limit": limit, "offset": offset, "items": items})


@router.get("/themes")
async def list_themes():
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
    return repository.report_list(limit=limit)


@router.get("/reports/{date}")
async def get_report(date: str):
    from datetime import datetime
    from app import config
    if date == "today":
        date = datetime.now(config.KST).strftime("%Y-%m-%d")
    report = repository.report_get(date)
    if not report:
        return JSONResponse({"error": "리포트 없음"}, status_code=404)
    return report


@router.get("/dashboard/sentiment")
async def dashboard_sentiment(days: int = Query(7, ge=1, le=30)):
    return JSONResponse({
        "today": sentiment.sentiment_today(),
        "trend": sentiment.sentiment_trend(days=days),
    })
