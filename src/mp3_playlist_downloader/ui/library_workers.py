"""Thread-pool workers for scanning, explicit file actions and downloads."""

from __future__ import annotations

import threading
from dataclasses import replace

from PySide6.QtCore import QObject, QRunnable, Signal

from .. import db, library, queue
from ..settings import Settings


class ScanSignals(QObject):
    completed = Signal(int, object, str)


class ScanWorker(QRunnable):
    def __init__(self, playlist_id: int) -> None:
        super().__init__()
        self.playlist_id = playlist_id
        self.signals = ScanSignals()

    def run(self) -> None:
        try:
            connection = db.connect()
            try:
                result = library.scan_folder(connection, self.playlist_id)
            finally:
                connection.close()
            self.signals.completed.emit(self.playlist_id, result, "")
        except Exception:
            self.signals.completed.emit(self.playlist_id, None, "The playlist folder could not be scanned.")


class ActionSignals(QObject):
    completed = Signal(int, int)


class ActionWorker(QRunnable):
    """Apply only explicitly confirmed user actions, reporting per-file failures."""

    def __init__(self, actions: list[tuple[str, int]]) -> None:
        super().__init__()
        self.actions = actions
        self.signals = ActionSignals()

    def run(self) -> None:
        succeeded = failed = 0
        try:
            connection = db.connect()
            try:
                for action, row_id in self.actions:
                    try:
                        if action == "keep_extra":
                            library.keep_extra(connection, row_id)
                        elif action == "delete_extra":
                            library.delete_extra(connection, row_id)
                        elif action == "delete_track":
                            library.delete_track(connection, row_id)
                        else:
                            raise ValueError("Unknown action")
                        succeeded += 1
                    except Exception:
                        failed += 1
            finally:
                connection.close()
        except Exception:
            failed += len(self.actions) - succeeded - failed
        self.signals.completed.emit(succeeded, failed)


class QueueSignals(QObject):
    progress = Signal(float, object, object)
    track_started = Signal(int, str)
    track_finished = Signal(int, bool, str)
    completed = Signal(object, str)


class RecoverySignals(QObject):
    completed = Signal(int, str)


class RecoveryWorker(QRunnable):
    def __init__(self) -> None:
        super().__init__()
        self.signals = RecoverySignals()

    def run(self) -> None:
        try:
            connection = db.connect()
            try:
                queue.recover_interrupted(connection)
                pending = queue.pending_count(connection)
            finally:
                connection.close()
            self.signals.completed.emit(pending, "")
        except Exception:
            self.signals.completed.emit(0, "Could not recover pending downloads.")


class QueueWorker(QRunnable):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = replace(settings)
        self.signals = QueueSignals()
        self.cancelled = threading.Event()

    def cancel(self) -> None:
        self.cancelled.set()

    def run(self) -> None:
        try:
            connection = db.connect()
            try:
                summary = queue.run_queue(connection, self.settings, cancelled=self.cancelled.is_set,
                    progress=self.signals.progress.emit, started=self.signals.track_started.emit,
                    finished=self.signals.track_finished.emit)
            finally:
                connection.close()
            self.signals.completed.emit(summary, "")
        except Exception:
            self.signals.completed.emit(None, "The download queue stopped unexpectedly. Progress is saved.")
