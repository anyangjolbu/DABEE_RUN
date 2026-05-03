# app/core/scheduler.py
"""
백그라운드 파이프라인 스케줄러.

asyncio 기반. settings.schedule_interval_minutes 마다 pipeline.run_once를
워커 스레드(asyncio.to_thread)에서 실행합니다.

특징:
    - 단일 인스턴스 보장: 이전 사이클이 안 끝났으면 다음 사이클은 스킵
    - 시작 시 즉시 1회 실행
    - 정상 종료 시 진행 중인 사이클이 끝날 때까지 대기
    - 다음 실행까지 남은 시간을 1초마다 WS로 브로드캐스트

상태:
    "idle"     : 대기 중 (다음 실행까지 카운트다운)
    "running"  : 파이프라인 실행 중
    "stopped"  : 비활성
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from app import config
from app.core.ws_manager import manager
from app.services import pipeline, settings_store

logger = logging.getLogger(__name__)


class Scheduler:
    """싱글톤 스케줄러."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._running_pipeline: bool = False
        self._stop_event: asyncio.Event = asyncio.Event()
        self._next_run_at: Optional[datetime] = None
        self.last_result: Optional[dict] = None
        self.last_run_at: Optional[datetime] = None
        self.cycle_count: int = 0

    # ── 상태 조회 ────────────────────────────────────────────
    @property
    def is_active(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def is_running_pipeline(self) -> bool:
        return self._running_pipeline

    def status(self) -> dict:
        if self._running_pipeline:
            phase = "running"
        elif self.is_active:
            phase = "idle"
        else:
            phase = "stopped"

        next_in_sec: Optional[int] = None
        if self._next_run_at and not self._running_pipeline:
            delta = (self._next_run_at - datetime.now(config.KST)).total_seconds()
            next_in_sec = max(0, int(delta))

        return {
            "phase":          phase,
            "cycle_count":    self.cycle_count,
            "last_run_at":    self.last_run_at.isoformat() if self.last_run_at else None,
            "next_run_at":    self._next_run_at.isoformat() if self._next_run_at else None,
            "next_in_sec":    next_in_sec,
            "last_result":    self.last_result,
        }

    # ── 시작/종료 ────────────────────────────────────────────
    async def start(self) -> None:
        if self.is_active:
            logger.info("스케줄러 이미 실행 중")
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="scheduler")
        logger.info("🟢 스케줄러 시작")

    async def stop(self) -> None:
        if not self.is_active:
            return
        logger.info("🔴 스케줄러 종료 요청")
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=60)
        except asyncio.TimeoutError:
            logger.warning("스케줄러 종료 타임아웃 — 강제 cancel")
            self._task.cancel()
        self._task = None
        logger.info("스케줄러 종료 완료")

    async def trigger_now(self) -> None:
        """즉시 1회 실행을 큐잉 (백그라운드)."""
        if self._running_pipeline:
            logger.info("이미 실행 중 — 트리거 무시")
            return
        asyncio.create_task(self._run_once())

    # ── 내부 루프 ────────────────────────────────────────────
    async def _loop(self) -> None:
        # 시작 시 즉시 1회
        await self._run_once()

        while not self._stop_event.is_set():
            settings = settings_store.load_settings()
            interval = max(1, int(settings.get("schedule_interval_minutes", 10)))
            self._next_run_at = datetime.now(config.KST) + timedelta(minutes=interval)

            # interval 동안 1초씩 쪼개서 대기 (정지 신호 즉시 반응)
            for _ in range(interval * 60):
                if self._stop_event.is_set():
                    return
                await asyncio.sleep(1)

            await self._run_once()

    async def _run_once(self) -> None:
        if self._running_pipeline:
            return
        self._running_pipeline = True
        self._next_run_at = None
        try:
            await manager.broadcast({
                "type":  "pipeline",
                "phase": "start",
            })
            # 동기 함수를 워커 스레드에서 실행 → 이벤트 루프 블로킹 방지
            result = await asyncio.to_thread(pipeline.run_once)
            self.last_result  = result
            self.last_run_at  = datetime.now(config.KST)
            self.cycle_count += 1
            await manager.broadcast({
                "type":   "pipeline",
                "phase":  "done",
                "result": result,
            })
        except Exception as e:
            logger.error(f"❌ 스케줄러 실행 중 예외: {e}", exc_info=True)
            await manager.broadcast({
                "type":  "pipeline",
                "phase": "error",
                "error": str(e),
            })
        finally:
            self._running_pipeline = False


# ── 전역 인스턴스 ────────────────────────────────────────────
scheduler = Scheduler()
