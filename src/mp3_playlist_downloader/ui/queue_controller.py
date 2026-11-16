"""Coordinate sequential downloads and startup recovery without blocking Qt."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QThreadPool, QTimer, Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton

from .. import db, paths, queue
from ..youtube.errors import YouTubeError
from .library_workers import QueueWorker, RecoveryWorker


class QueueController(QObject):
    def __init__(self, window, layout) -> None:
        super().__init__(window)
        self.window = window
        self.worker: QueueWorker | None = None
        self.recovery: RecoveryWorker | None = None
        self.pending = 0
        self.total = 0
        self.finished_count = 0
        self.current_title = ""
        self.close_after_cancel = False
        self._deadline: datetime | None = None
        self._auto_allowed = False
        self._clock = lambda: datetime.now(timezone.utc)
        self._countdown = QTimer(self)
        self._countdown.setInterval(1000)
        self._countdown.timeout.connect(self._tick_countdown)
        self.banner = QLabel("")
        self.resume_button = QPushButton("Resume")
        self.dismiss_button = QPushButton("Dismiss")
        banner = QHBoxLayout()
        banner.addWidget(self.banner, 1)
        banner.addWidget(self.resume_button)
        banner.addWidget(self.dismiss_button)
        layout.addLayout(banner)
        self.banner.hide()
        self.resume_button.hide()
        self.dismiss_button.hide()
        self.resume_button.clicked.connect(self.resume)
        self.dismiss_button.clicked.connect(self.hide_banner)
        progress = QHBoxLayout()
        self.progress_label = QLabel("Ready")
        self.progress_label.setTextFormat(Qt.TextFormat.PlainText)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        progress.addWidget(self.progress_label)
        progress.addWidget(self.progress_bar, 1)
        progress.addWidget(self.cancel_button)
        layout.addLayout(progress)

    def _recover(self) -> None:
        self.recovery = RecoveryWorker()
        self.recovery.signals.completed.connect(self._recovered)
        self.window.update_actions()
        QThreadPool.globalInstance().start(self.recovery)

    def _recovered(self, pending: int, error: str) -> None:
        self.recovery = None
        self.pending = pending
        if error:
            self.window.warning_banner.setText(error)
            self.window.warning_banner.show()
        elif pending:
            self.show_banner(f"{pending} downloads pending — Resume")
        self.window.update_actions()

    def show_banner(self, message: str) -> None:
        self.banner.setText(message)
        self.resume_button.setText("Resume")
        self.banner.show()
        self.resume_button.show()
        self.dismiss_button.show()

    def hide_banner(self) -> None:
        self._countdown.stop()
        self._deadline = None
        self._auto_allowed = False
        self.banner.hide()
        self.resume_button.hide()
        self.dismiss_button.hide()

    def _arm_countdown(self, state: queue.PauseState) -> None:
        try:
            deadline = datetime.fromisoformat(state.until)
            if deadline.tzinfo is None:
                raise ValueError("Naive deadline")
        except ValueError:
            self.show_banner("YouTube is rate-limiting downloads. Progress saved — Resume now.")
            return
        self._deadline = deadline
        self._auto_allowed = state.auto_retry_allowed
        self.resume_button.setText("Resume now")
        self.banner.show()
        self.resume_button.show()
        self.dismiss_button.show()
        self._countdown.start()
        self._tick_countdown()

    def _tick_countdown(self) -> None:
        if self._deadline is None:
            return
        remaining = max(0, math.ceil((self._deadline - self._clock()).total_seconds()))
        hours, rem = divmod(remaining, 3600)
        minutes, seconds = divmod(rem, 60)
        suffix = f"Retry in {hours:02d}:{minutes:02d}:{seconds:02d}." if remaining else "Cooldown ended."
        if not self._auto_allowed:
            suffix += " Automatic retry limit reached; resume manually."
        self.banner.setText("YouTube is rate-limiting downloads. Progress saved. " + suffix + " Configure cookies in Settings → YouTube if this persists.")
        if remaining == 0:
            if self._auto_allowed and self.window.settings.auto_resume_after_rate_limit:
                self.resume(automatic=True)
            else:
                self._countdown.stop()

    def start_missing(self) -> None:
        if self.window.selected_id is None or self.window.queue_running or self.window.equalizing or self.window.editing or self.recovery is not None:
            return
        if not paths.find_tool("ffmpeg", self.window.settings.ffmpeg_path):
            QMessageBox.warning(self.window, "ffmpeg required", "ffmpeg not found. Install it or set its path in Settings → Tools.")
            return
        connection = db.connect()
        try:
            include_existing = self.window.settings.overwrite_existing
            count = queue.existing_count(connection, self.window.selected_id) if include_existing else 0
            if count:
                answer = QMessageBox.question(self.window, "Replace existing tracks", f"{count} existing tracks will be replaced. Continue?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return
            try:
                queue.enqueue_missing(connection, self.window.selected_id, self.window.settings, include_existing=include_existing)
            except YouTubeError as error:
                QMessageBox.warning(self.window, "ffmpeg required", str(error))
                return
            self.pending = queue.pending_count(connection)
            if self.pending:
                queue.clear_pause(connection, manual=True)
        finally:
            connection.close()
        if self.pending:
            self._start()

    def redownload(self, video_id: int) -> None:
        """Explicitly requeue one track; the overwrite decision survives restart."""
        if self.window.queue_running or self.window.equalizing or self.window.editing or self.recovery is not None or self.window.library_controller.scans or self.window.library_controller.action is not None or self.window._refresh_worker is not None:
            return
        if not self.window.settings.overwrite_existing:
            answer = QMessageBox.question(self.window, "Re-download", "Re-download this track? Any tracked file will be moved to the Recycle Bin.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        connection = db.connect()
        try:
            try:
                queued = queue.enqueue_video(connection, video_id, self.window.settings)
            except YouTubeError as error:
                QMessageBox.warning(self.window, "ffmpeg required", str(error))
                return
            if not queued:
                return
            self.pending = queue.pending_count(connection)
            queue.clear_pause(connection, manual=True)
        finally:
            connection.close()
        self._start()

    def resume(self, automatic: bool = False) -> None:
        if self.window.queue_running or self.window.equalizing or self.window.editing or self.recovery is not None:
            return
        if self.window.library_controller.scans or self.window.library_controller.action is not None or self.window.library_controller.reviewing or self.window._refresh_worker is not None or (automatic and QApplication.activeModalWidget() is not None):
            return
        if not paths.find_tool("ffmpeg", self.window.settings.ffmpeg_path):
            if automatic:
                self._countdown.stop()
                self._auto_allowed = False
                self.window.warning_banner.setText("ffmpeg not found. Install it or set its path in Settings → Tools.")
                self.window.warning_banner.show()
                return
            QMessageBox.warning(self.window, "ffmpeg required", "ffmpeg not found. Install it or set its path in Settings → Tools.")
            return
        connection = db.connect()
        try:
            self.pending = queue.pending_count(connection)
            if self.pending:
                queue.clear_pause(connection, manual=not automatic)
        finally:
            connection.close()
        if self.pending:
            self._start()

    def _start(self) -> None:
        if self.window.equalizing or self.window.editing or self.window.library_controller.scans or self.window.library_controller.action is not None or self.window.library_controller.reviewing or self.window._refresh_worker is not None:
            return
        self.total, self.finished_count = self.pending, 0
        self.hide_banner()
        self.window.queue_running = True
        self.window.sidebar.set_busy(True)
        self.window.refresh_button.setEnabled(False)
        self.window.empty_add.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.window.update_actions()
        self.worker = QueueWorker(self.window.settings)
        self.worker.signals.track_started.connect(self._started)
        self.worker.signals.track_finished.connect(self._track_finished)
        self.worker.signals.progress.connect(self._progress)
        self.worker.signals.completed.connect(self._finished)
        QThreadPool.globalInstance().start(self.worker)

    def _started(self, video_id: int, title: str) -> None:
        self.current_title = title
        self._progress(0, None, None)

    def _progress(self, percent: float, speed, eta) -> None:
        percent = max(0.0, min(100.0, percent)) if math.isfinite(percent) else 0.0
        overall = (self.finished_count + percent / 100) * 100 / max(self.total, 1)
        self.progress_bar.setValue(int(overall))
        self.progress_bar.setFormat(f"Overall {overall:.0f}% · File {percent:.0f}%")
        text = f"{self.finished_count + 1}/{self.total} · Downloading {self.current_title}"
        if isinstance(speed, (int, float)) and math.isfinite(speed) and speed >= 0:
            text += f" · {speed / 1048576:.1f} MB/s" if speed >= 1048576 else f" · {speed / 1024:.1f} KB/s"
        if isinstance(eta, (int, float)) and math.isfinite(eta) and eta >= 0:
            seconds = int(eta)
            hours, rem = divmod(seconds, 3600)
            minutes, seconds = divmod(rem, 60)
            text += f" · ETA {hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f" · ETA {minutes:02d}:{seconds:02d}"
        self.progress_label.setText(text)
        self.window.statusBar().showMessage(text)

    def _track_finished(self, video_id: int, ok: bool, error: str) -> None:
        self.finished_count += 1
        self.progress_bar.setValue(int(self.finished_count * 100 / max(self.total, 1)))
        if self.window.selected_id is not None:
            self.window.select_playlist(self.window.selected_id, scan=False, preserve_selection=True)

    def cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.progress_label.setText("Cancelling…")

    def _finished(self, summary, error: str) -> None:
        self.worker = None
        self.window.queue_running = False
        self.window.sidebar.set_busy(False)
        self.window.empty_add.setEnabled(True)
        self.cancel_button.setEnabled(False)
        connection = db.connect()
        try:
            self.pending = queue.pending_count(connection)
            state = queue.pause_state(connection)
        finally:
            connection.close()
        if error:
            self.window.warning_banner.setText(error)
            self.window.warning_banner.show()
        elif summary:
            text = f"{summary.downloaded} downloaded, {summary.failed} failed, {summary.unavailable} unavailable"
            self.progress_label.setText(text)
            self.window.statusBar().showMessage(text)
            if not summary.rate_limited_until and self.pending:
                self.show_banner(f"{self.pending} downloads pending — Resume")
        if self.close_after_cancel:
            self.window.close()
            return
        if self.window.selected_id is not None:
            self.window.select_playlist(self.window.selected_id, scan=False, preserve_selection=True)
            self.window.library_controller.scan(self.window.selected_id)
        self.window.refresh_button.setEnabled(self.window.selected_id is not None)
        self.window.update_actions()
        if summary and summary.rate_limited_until:
            self._arm_countdown(state)
