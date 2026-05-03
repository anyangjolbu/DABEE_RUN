# app/main.py
"""
FastAPI 진입점.

이 파일은 다음을 담당:
- 앱 인스턴스 생성
- 시작/종료 lifespan (DB 초기화, 스케줄러 시작/종료, WS 로그 핸들러 부착)
- 라우터 등록 (public, admin, ws)
- Jinja2 템플릿 + 정적 파일 마운트
- 루트 페이지 (대시보드 렌더)

비즈니스 로직은 app/services/, 라우팅 상세는 app/api/.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import config
from app.api import admin as admin_router
from app.api import public as public_router
from app.api import ws as ws_router
from app.api.admin import get_session
from app.core.db import init_db
from app.core.logging_setup import setup_logging
from app.core.scheduler import scheduler
from app.core.ws_manager import attach_ws_log_handler


# ── 로깅을 가장 먼저 ──────────────────────────────────────────
setup_logging()
logger = logging.getLogger(__name__)


# ── 라이프스팬 ────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ─ 시작 ─
    logger.info("=" * 60)
    logger.info("DABEE Run 시작")
    logger.info(f"DATA_DIR = {config.DATA_DIR}")
    logger.info(f"DB_PATH  = {config.DB_PATH}")

    for w in config.validate():
        logger.warning(f"⚠️  {w}")

    init_db()
    attach_ws_log_handler()

    # STEP-3B-14: settings.search_themes에 맞춰 articles.track 백필
    # 구 데이터(track 누락 시 monitor 기본)로 인해 경쟁사/업계 기사가
    # monitor로 잘못 저장돼 있는 케이스를 일괄 정정.
    try:
        from app.core import models
        from app.core.db import get_conn
        from app.services.settings_store import load_settings
        themes = load_settings().get("search_themes", {})
        with get_conn() as conn:
            n = models.backfill_articles_track(conn, themes)
        if n:
            logger.info(f"✅ articles.track 백필: 총 {n}건 갱신")
    except Exception as e:
        logger.warning(f"⚠️ articles.track 백필 실패(skip): {e}")

    await scheduler.start()

    logger.info("=" * 60)
    yield
    # ─ 종료 ─
    logger.info("DABEE Run 종료 시작")
    await scheduler.stop()
    logger.info("DABEE Run 종료 완료")


# ── 앱 ────────────────────────────────────────────────────────
app = FastAPI(
    title="DABEE Run",
    description="SK하이닉스 PR팀 뉴스 모니터링",
    version="3.0.0",
    lifespan=lifespan,
)

# 정적 파일
WEB_ROOT = Path(__file__).resolve().parent / "web"
app.mount("/static", StaticFiles(directory=WEB_ROOT / "static"), name="static")

# 템플릿
templates = Jinja2Templates(directory=str(WEB_ROOT / "templates"))

# 라우터
app.include_router(public_router.router, prefix="/api",       tags=["public"])
app.include_router(admin_router.router,  prefix="/api/admin", tags=["admin"])
app.include_router(ws_router.router,                          tags=["websocket"])


# ── 페이지 ────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def page_home(request: Request):
    return templates.TemplateResponse(
        "public/dashboard.html",
        {"request": request, "active": "home"},
    )


@app.get("/feed", response_class=HTMLResponse)
async def page_feed(request: Request):
    return templates.TemplateResponse(
        "public/feed.html",
        {"request": request, "active": "feed"},
    )


@app.get("/report", response_class=HTMLResponse)
async def page_report(request: Request):
    return templates.TemplateResponse(
        "public/report.html",
        {"request": request, "active": "report"},
    )


# ── 관리자 페이지 ──────────────────────────────────────────────
@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    if get_session(request):
        return RedirectResponse("/admin")
    return templates.TemplateResponse("admin/login.html", {"request": request})


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard_page(request: Request):
    if not get_session(request):
        return RedirectResponse("/admin/login")
    return templates.TemplateResponse(
        "admin/dashboard.html", {"request": request, "active": "dashboard"}
    )


@app.get("/admin/keywords", response_class=HTMLResponse)
async def admin_keywords_page(request: Request):
    if not get_session(request):
        return RedirectResponse("/admin/login")
    return templates.TemplateResponse(
        "admin/keywords.html", {"request": request, "active": "keywords"}
    )


@app.get("/admin/recipients", response_class=HTMLResponse)
async def admin_recipients_page(request: Request):
    if not get_session(request):
        return RedirectResponse("/admin/login")
    return templates.TemplateResponse(
        "admin/recipients.html", {"request": request, "active": "recipients"}
    )
