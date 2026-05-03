# app/api/ws.py
"""
WebSocket 엔드포인트.

클라이언트가 /ws에 연결하면 실시간 로그·통계·파이프라인 이벤트를
받습니다. 클라이언트 측 메시지는 사용하지 않으므로 receive는
연결 유지용으로만 호출.
"""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.ws_manager import manager
from app.core.scheduler import scheduler

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)

    # 연결 직후 현재 상태 1회 push
    try:
        await ws.send_json({
            "type": "scheduler",
            "data": scheduler.status(),
        })
    except Exception:
        pass

    try:
        while True:
            # 클라이언트 메시지는 무시하지만, 연결 유지를 위해 수신은 함
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=5)
            except asyncio.TimeoutError:
                # 5초마다 ping 대신 스케줄러 상태 push
                try:
                    await ws.send_json({
                        "type": "scheduler",
                        "data": scheduler.status(),
                    })
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(ws)
