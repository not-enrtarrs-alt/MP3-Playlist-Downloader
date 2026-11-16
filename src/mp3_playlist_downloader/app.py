"""QApplication bootstrap and single-instance protection."""

from __future__ import annotations

import logging
import sqlite3
import sys

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from . import db, paths, settings
from .logging_setup import LogBridge, setup_logging
from .ui.main_window import MainWindow
from .ui.theme import apply_theme


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("MP3 Playlist Downloader")
    app.setFont(QFont("Segoe UI", 10))
    try:
        paths.data_dir().mkdir(parents=True, exist_ok=True)
    except OSError:
        QMessageBox.critical(None, "MP3 Playlist Downloader", "The application data folder is not writable.")
        return 2
    lock = QLockFile(str(paths.data_dir() / "app.lock"))
    if not lock.tryLock(0):
        QMessageBox.warning(None, "MP3 Playlist Downloader", "Another instance is already running, or the application lock is unavailable.")
        return 2
    try:
        bridge = LogBridge()
        try:
            setup_logging(bridge)
            loaded = settings.load()
            connection = db.connect()
            try:
                db.initialize(connection)
            finally:
                connection.close()
        except (OSError, sqlite3.Error, RuntimeError):
            QMessageBox.critical(None, "MP3 Playlist Downloader", "The application data or database could not be initialized.")
            return 2
        apply_theme(app, loaded.settings.theme)
        window = MainWindow(loaded.settings, loaded.warnings)
        bridge.line.connect(window.append_log)
        window.show()
        logging.getLogger(__name__).info("Application started")
        return app.exec()
    finally:
        lock.unlock()
