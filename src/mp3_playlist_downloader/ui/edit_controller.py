"""Background manual-link and album-retag operations."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from .. import db, services
from ..linking import LinkCancelled, LinkError
from ..renaming import RenameCancelled, RenameError
from ..settings import Settings
from ..youtube.parse import title_and_artist


class EditSignals(QObject):
    progress = Signal(int, int, str)
    completed = Signal(object, str)


class EditWorker(QRunnable):
    def __init__(self, operation: str, row_id: int, settings: Settings, source: str = "") -> None:
        super().__init__()
        self.operation, self.row_id, self.source = operation, row_id, source
        self.settings = replace(settings)
        self.cancelled = threading.Event()
        self.signals = EditSignals()

    def cancel(self) -> None:
        self.cancelled.set()

    def run(self) -> None:
        try:
            connection = db.connect()
            try:
                if self.operation == "link":
                    result = services.link_file(connection, self.row_id, Path(self.source), self.settings, cancelled=self.cancelled.is_set)
                elif self.operation == "rename":
                    result = services.rename_track(connection, self.row_id, self.source, cancelled=self.cancelled.is_set)
                elif self.operation == "album":
                    result = services.sync_album(connection, self.row_id, cancelled=self.cancelled.is_set, progress=self.signals.progress.emit)
                else:
                    raise ValueError("Unknown file operation.")
            finally:
                connection.close()
            self.signals.completed.emit(result, "")
        except (LinkCancelled, RenameCancelled):
            self.signals.completed.emit(None, "Cancelled.")
        except (LinkError, RenameError) as error:
            self.signals.completed.emit(None, str(error))
        except Exception:
            self.signals.completed.emit(None, "The file operation could not be completed.")


class EditController(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.worker: EditWorker | None = None
        self.operation = ""
        self.close_after_cancel = False

    def _blocked(self) -> bool:
        return bool(self.window.queue_running or self.window.equalizing or self.window.editing or self.window._refresh_worker is not None or self.window.library_controller.action is not None or self.window.library_controller.scans or self.window.library_controller.reviewing or self.window.queue_controller.recovery is not None)

    def point_to_file(self, video_id: int) -> None:
        if self._blocked():
            return
        row = next((row for row in self.window.track_model.rows if not row.get("_extra") and row["id"] == video_id), None)
        if row is None:
            return
        source, _ = QFileDialog.getOpenFileName(self.window, "Point to MP3 file", "", "MP3 files (*.mp3)")
        if not source:
            return
        if row.get("downloaded"):
            answer = QMessageBox.question(self.window, "Replace tracked file", "Replace or re-tag this track's existing file?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._start("link", video_id, source)

    def sync_album(self) -> None:
        if self._blocked() or self.window.selected_id is None:
            return
        self._start("album", self.window.selected_id)

    def rename_track(self, video_id: int) -> None:
        if self._blocked():
            return
        row = next((row for row in self.window.track_model.rows if not row.get("_extra") and row["id"] == video_id), None)
        if row is None or row.get("download_state") == "downloading":
            return
        current, _ = title_and_artist(row.get("title", ""), row.get("uploader"), row.get("custom_title"))
        title, accepted = QInputDialog.getText(self.window, "Rename track", "Track title:", text=current)
        if accepted:
            self._start("rename", video_id, title)

    def _start(self, operation: str, row_id: int, source: str = "") -> None:
        self.operation = operation
        self.window.editing = True
        self.window.sidebar.set_busy(True)
        self.window.refresh_button.setEnabled(False)
        self.window.empty_add.setEnabled(False)
        self.window.queue_controller.cancel_button.setEnabled(True)
        self.window.queue_controller.progress_bar.setValue(0)
        self.window.queue_controller.progress_bar.setFormat("%p%")
        label = {"link": "Linking MP3…", "rename": "Renaming track…", "album": "Updating album tags…"}[operation]
        self.window.queue_controller.progress_label.setText(label)
        self.window.update_actions()
        self.worker = EditWorker(operation, row_id, self.window.settings, source)
        self.worker.signals.progress.connect(self._progress)
        self.worker.signals.completed.connect(self._finished)
        QThreadPool.globalInstance().start(self.worker)

    def _progress(self, current: int, total: int, title: str) -> None:
        self.window.queue_controller.progress_label.setText(f"{current}/{total} · Updating album: {title}")
        self.window.queue_controller.progress_bar.setValue(int((current - 1) * 100 / max(total, 1)))

    def cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.window.queue_controller.cancel_button.setEnabled(False)
            self.window.queue_controller.progress_label.setText("Finishing the current file…")

    def _finished(self, result, error: str) -> None:
        self.worker = None
        self.window.editing = False
        self.window.sidebar.set_busy(False)
        self.window.empty_add.setEnabled(True)
        self.window.refresh_button.setEnabled(self.window.selected_id is not None)
        self.window.queue_controller.cancel_button.setEnabled(False)
        if error and error != "Cancelled.":
            self.window.warning_banner.setText(error)
            self.window.warning_banner.show()
        elif error:
            self.window.statusBar().showMessage(error)
        elif self.operation in ("link", "rename"):
            self.window.queue_controller.progress_bar.setValue(100)
            self.window.statusBar().showMessage("Track renamed." if self.operation == "rename" else "MP3 linked.")
            if result.warning:
                self.window.warning_banner.setText(result.warning)
                self.window.warning_banner.show()
        else:
            completed = result.succeeded + result.failed
            self.window.queue_controller.progress_bar.setValue(int(completed * 100 / max(result.total, 1)) if result.cancelled else 100)
            text = f"Album tags: {result.succeeded} updated, {result.failed} failed"
            if result.cancelled:
                text += " · Cancelled"
            if result.stale:
                text += " · Playlist title changed"
            self.window.statusBar().showMessage(text)
            if result.failed or result.stale:
                self.window.warning_banner.setText(text)
                self.window.warning_banner.show()
        if self.close_after_cancel:
            self.window.close()
            return
        if self.window.selected_id is not None:
            self.window.select_playlist(self.window.selected_id, scan=False, preserve_selection=True)
            self.window.library_controller.scan(self.window.selected_id)
        self.window.update_actions()
