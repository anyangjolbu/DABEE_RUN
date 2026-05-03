# app/main.py
"""
FastAPI 진입점.

이 파일은 다음만 담당합니다:
- 앱 인스턴스 생성
- 시작/종료 이벤트 (DB 초기화 등)
- 라우터 등록 (현재는 health 하나)

비즈니스 로직은 app/services/, 라우팅 상세는 app/api/ 에 위치.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app import config
from app.core.db import init_db
from app.core.logging_setup import setup_logging


# ── 로깅을 가장 먼저 초기화 ──────────────────────────────────────────
setup_logging()
logger = logging.getLogger(__name__)


# ── 라이프스팬 (앱 시작/종료 훅) ─────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 시작 시
    logger.info("=" * 60)
    logger.info("DABEE Run 시작")
    logger.info(f"DATA_DIR = {config.DATA_DIR}")
    logger.info(f"DB_PATH  = {config.DB_PATH}")

    # 환경변수 누락 경고
    for w in config.validate():
        logger.warning(f"⚠️  {w}")

    # DB 초기화 (테이블 자동 생성)
    init_db()

    logger.info("=" * 60)
    yield
    # 종료 시
    logger.info("DABEE Run 종료")


# ── 앱 인스턴스 ──────────────────────────────────────────────────────
app = FastAPI(
    title="DABEE Run",
    description="SK하이닉스 PR팀 뉴스 모니터링",
    version="2.0.0",
    lifespan=lifespan,
)


# ── 헬스체크 ─────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    """
    Railway healthcheckPath 및 운영 모니터링용.
    DB가 정상 응답하는지까지 확인합니다.
    """
    from app.core.db import get_conn
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1").fetchone()
        return JSONResponse({"status": "ok", "db": "ok"})
    except Exception as e:
        logger.error(f"헬스체크 DB 실패: {e}")
        return JSONResponse(
            {"status": "error", "db": "fail", "error": str(e)},
            status_code=503,
        )


# ── 임시 루트 (다음 단계에서 대시보드로 교체) ────────────────────────
@app.get("/")
async def root():
    return JSONResponse({
        "service": "DABEE Run",
        "version": "2.0.0",
        "message": "STEP 1 동작 확인용 응답입니다. 곧 대시보드로 교체됩니다.",
    })
