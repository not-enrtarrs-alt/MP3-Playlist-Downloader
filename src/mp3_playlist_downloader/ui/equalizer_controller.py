"""Sequential equalization worker and responsive Qt coordination."""

from __future__ import annotations

import threading
from dataclasses import replace

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import QMessageBox

from .. import db, equalizer, services
from ..settings import Settings


class EqualizeSignals(QObject):
    progress = Signal(int, int, str)
    completed = Signal(object, str)


class EqualizeWorker(QRunnable):
    def __init__(self, video_ids: list[int], settings: Settings) -> None:
        super().__init__()
        self.video_ids = video_ids
        self.settings = replace(settings)
        self.cancelled = threading.Event()
        self.signals = EqualizeSignals()

    def cancel(self) -> None:
        self.cancelled.set()

    def run(self) -> None:
        try:
            connection = db.connect()
            try:
                summary = services.equalize_tracks(connection, self.video_ids, self.settings,
                    cancelled=self.cancelled.is_set, progress=self.signals.progress.emit)
            finally:
                connection.close()
            self.signals.completed.emit(summary, "")
        except equalizer.EqualizerMissing:
            self.signals.completed.emit(None, equalizer.MISSING_MESSAGE)
        except Exception:
            self.signals.completed.emit(None, "Equalization could not be completed.")


class EqualizerController(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.worker: EqualizeWorker | None = None
        self.close_after_cancel = False

    def eligible(self) -> list[int]:
        return [row["id"] for index, row in enumerate(self.window.track_model.rows)
                if index in self.window.track_model.checked and not row.get("_extra") and row.get("downloaded")
                and not row.get("equalized") and row.get("file_path")]

    def show_missing(self) -> None:
        dialog = QMessageBox(self.window)
        dialog.setWindowTitle("mp3gain not found")
        dialog.setText(equalizer.MISSING_MESSAGE)
        settings_button = dialog.addButton("Open Settings", QMessageBox.ButtonRole.ActionRole)
        dialog.addButton(QMessageBox.StandardButton.Close)
        dialog.exec()
        if dialog.clickedButton() == settings_button:
            self.window.settings_controller.open("Tools")

    def start(self, video_ids: list[int] | None = None) -> None:
        if self.window.queue_running or self.window.equalizing or self.window.editing or self.window.library_controller.scans or self.window.library_controller.action is not None or self.window.library_controller.reviewing or self.window._refresh_worker is not None:
            return
        selected = self.eligible() if video_ids is None else video_ids
        if not selected:
            return
        if not equalizer.discover(self.window.settings):
            self.show_missing()
            return
        self.window.equalizing = True
        self.window.sidebar.set_busy(True)
        self.window.refresh_button.setEnabled(False)
        self.window.empty_add.setEnabled(False)
        self.window.queue_controller.cancel_button.setEnabled(True)
        self.window.queue_controller.progress_bar.setValue(0)
        self.window.queue_controller.progress_bar.setFormat("%p%")
        self.window.update_actions()
        self.worker = EqualizeWorker(selected, self.window.settings)
        self.worker.signals.progress.connect(self._progress)
        self.worker.signals.completed.connect(self._finished)
        QThreadPool.globalInstance().start(self.worker)

    def cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.window.queue_controller.cancel_button.setEnabled(False)
            self.window.queue_controller.progress_label.setText("Cancelling after the current file…")

    def _progress(self, current: int, total: int, title: str) -> None:
        self.window.queue_controller.progress_label.setText(f"{current}/{total} · Equalizing {title}")
        self.window.queue_controller.progress_bar.setValue(int((current - 1) * 100 / max(total, 1)))

    def _finished(self, summary, error: str) -> None:
        self.worker = None
        self.window.equalizing = False
        self.window.sidebar.set_busy(False)
        self.window.empty_add.setEnabled(True)
        self.window.refresh_button.setEnabled(self.window.selected_id is not None)
        self.window.queue_controller.cancel_button.setEnabled(False)
        if summary is not None:
            completed = summary.succeeded + summary.failed
            self.window.queue_controller.progress_bar.setValue(int(completed * 100 / max(summary.total, 1)) if summary.cancelled else 100)
            text = f"{summary.succeeded} succeeded, {summary.failed} failed"
            if summary.cancelled:
                text += " · Cancelled"
            self.window.queue_controller.progress_label.setText(text)
            self.window.statusBar().showMessage(text)
        elif error:
            self.window.warning_banner.setText(error)
            self.window.warning_banner.show()
        if self.close_after_cancel:
            self.window.close()
            return
        if self.window.selected_id is not None:
            self.window.select_playlist(self.window.selected_id, scan=False, preserve_selection=True)
            self.window.library_controller.scan(self.window.selected_id)
        self.window.update_actions()
