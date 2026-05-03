# app/core/logging_setup.py
"""
로깅 초기화.

- KST 시간대로 표시
- 파일(monitor.log) + 콘솔 동시 출력
- WebSocket 핸들러는 추후 STEP에서 추가
"""

import logging
from datetime import datetime

from app import config


class KSTFormatter(logging.Formatter):
    """asctime을 KST로 표시하는 포매터."""

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=config.KST)
        return dt.strftime(datefmt or "%Y-%m-%d %H:%M:%S")


def setup_logging() -> None:
    """앱 시작 시 1회 호출."""
    fmt = KSTFormatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    )

    file_handler = logging.FileHandler(config.LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))

    # 중복 방지: --reload로 인한 재초기화 시 핸들러가 쌓이지 않도록 정리
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
