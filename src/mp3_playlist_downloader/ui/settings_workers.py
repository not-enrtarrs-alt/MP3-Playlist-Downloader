"""Explicit, background-only settings diagnostics."""

from __future__ import annotations

import subprocess
from dataclasses import replace

from PySide6.QtCore import QObject, QRunnable, Signal

from .. import equalizer
from ..logging_setup import redact
from ..settings import Settings
from ..youtube.client import fetch_playlist
from ..youtube.errors import YouTubeError


class TestSignals(QObject):
    completed = Signal(bool, str)


class CookieTestWorker(QRunnable):
    def __init__(self, url: str, settings: Settings) -> None:
        super().__init__()
        self.url = url
        self.settings = replace(settings)
        self.signals = TestSignals()

    def run(self) -> None:
        try:
            fetch_playlist(self.url, self.settings)
            self.signals.completed.emit(True, "Cookie test succeeded.")
        except YouTubeError as error:
            self.signals.completed.emit(False, str(error))
        except Exception:
            self.signals.completed.emit(False, "Cookie test failed. Check your connection and cookie settings.")


class GainHelpWorker(QRunnable):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = replace(settings)
        self.signals = TestSignals()

    def run(self) -> None:
        executable = equalizer.discover(self.settings)
        if not executable:
            self.signals.completed.emit(False, equalizer.MISSING_MESSAGE)
            return
        try:
            result = subprocess.run([executable, "/?"], capture_output=True, text=True, errors="replace",
                                    timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            output = redact((result.stdout or "") + (result.stderr or ""))[:4000]
            self.signals.completed.emit(True, output or "mp3gain returned no help text.")
        except (OSError, subprocess.TimeoutExpired):
            self.signals.completed.emit(False, "mp3gain help could not be read.")
