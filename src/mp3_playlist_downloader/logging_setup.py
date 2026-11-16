"""Rotating logs and a Qt signal bridge with basic secret redaction."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QObject, Signal

from .paths import log_dir
from .redaction import redact


class SafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class LogBridge(QObject):
    """Signals log lines to a GUI drawer, including across threads."""

    line = Signal(str)


class QtLogHandler(logging.Handler):
    def __init__(self, bridge: LogBridge) -> None:
        super().__init__()
        self.bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.bridge.line.emit(self.format(record))
        except Exception:
            self.handleError(record)


def setup_logging(bridge: LogBridge | None = None) -> None:
    """Configure the application's own logger without changing host loggers."""
    folder = log_dir()
    folder.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("mp3_playlist_downloader")
    logger.setLevel(logging.DEBUG if os.environ.get("MP3PD_DEBUG") == "1" else logging.INFO)
    logger.propagate = False
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    formatter = SafeFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(folder / "app.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    if bridge is not None:
        qt_handler = QtLogHandler(bridge)
        qt_handler.setFormatter(formatter)
        logger.addHandler(qt_handler)
