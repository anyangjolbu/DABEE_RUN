# app/core/ws_manager.py
"""
WebSocket 연결 관리 + 실시간 로그 브로드캐스트.

웹 페이지에 실시간 로그·통계·파이프라인 진행률을 흘려보냅니다.
연결된 모든 클라이언트에게 동시 전송하므로, 여러 브라우저 탭에서
같은 화면을 봐도 동기화됩니다.

이벤트 형식:
    {"type": "log",      "level": "INFO", "message": "..."}
    {"type": "stats",    "data": {...}}
    {"type": "pipeline", "phase": "collect", "...": ...}
"""

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WSManager:
    """WebSocket 연결 풀."""

    def __init__(self) -> None:
        self.active: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.active.append(ws)
        logger.info(f"WS 연결 ({len(self.active)}개 활성)")

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self.active:
                self.active.remove(ws)
        logger.info(f"WS 종료 ({len(self.active)}개 활성)")

    async def broadcast(self, payload: dict[str, Any]) -> None:
        """연결된 모든 클라이언트에 전송. 끊긴 연결은 자동 제거."""
        text = json.dumps(payload, ensure_ascii=False)
        dead: list[WebSocket] = []
        async with self._lock:
            for ws in self.active:
                try:
                    await ws.send_text(text)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                if ws in self.active:
                    self.active.remove(ws)


# ── 전역 매니저 인스턴스 ─────────────────────────────────────
manager = WSManager()


# ── 로깅 핸들러 ──────────────────────────────────────────────
class WSLogHandler(logging.Handler):
    """
    Python logging 메시지를 WebSocket으로 흘려보내는 핸들러.

    asyncio 루프가 돌고 있을 때만 동작하고, 동기 컨텍스트에서는
    조용히 무시합니다 (예: 모듈 초기화 시점).
    """

    # WS로 보내지 않을 로거 (피드백 루프 + 노이즈 방지)
    WS_LOG_BLACKLIST = (
        "websockets",
        "uvicorn.access",
        "uvicorn.error",
        "watchfiles",
        "app.core.ws_manager",  # 자기 자신
    )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # 블랙리스트 로거는 WS로 안 보냄
            for blocked in self.WS_LOG_BLACKLIST:
                if record.name.startswith(blocked):
                    return
            msg = self.format(record)
            payload = {
                "type":    "log",
                "level":   record.levelname,
                "message": msg,
            }
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # 동기 컨텍스트 → 스킵
                return
            loop.create_task(manager.broadcast(payload))
        except Exception:
            pass


def attach_ws_log_handler() -> None:
    """루트 로거에 WebSocket 핸들러를 추가. 앱 시작 시 1회 호출."""
    handler = WSLogHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.getLogger().addHandler(handler)
