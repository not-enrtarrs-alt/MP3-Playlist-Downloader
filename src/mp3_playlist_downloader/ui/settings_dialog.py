"""Tabbed settings editor with atomic save and optional background tests."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QTabWidget, QVBoxLayout

from .. import settings as settings_module
from ..settings import Settings, SettingsError
from .settings_tabs import AboutTab, GeneralTab, ToolsTab, YouTubeTab
from .settings_workers import CookieTestWorker, GainHelpWorker


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None, *, test_url: str | None = None) -> None:
        super().__init__(parent)
        self.original = replace(settings)
        self.result_settings: Settings | None = None
        self.test_url = test_url
        self.cookie_worker: CookieTestWorker | None = None
        self.gain_worker: GainHelpWorker | None = None
        self.setWindowTitle("Settings")
        self.resize(700, 500)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.general = GeneralTab(settings)
        self.youtube = YouTubeTab(settings)
        self.tools = ToolsTab(settings)
        self.about = AboutTab()
        for widget, label in ((self.general, "General"), (self.youtube, "YouTube"), (self.tools, "Tools"), (self.about, "About")):
            self.tabs.addTab(widget, label)
        layout.addWidget(self.tabs)
        self.error = QLabel("")
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.save_settings)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.youtube.test_button.clicked.connect(self.test_cookies)
        self.tools.test_button.clicked.connect(self.test_gain)

    def snapshot(self) -> Settings:
        """Return a draft without modifying the original settings object."""
        return replace(self.original, output_root=self.general.output_root.text().strip(),
            overwrite_existing=self.general.overwrite.isChecked(), auto_equalize=self.general.auto_equalize.isChecked(),
            confirm_delete=self.general.confirm_delete.isChecked(), theme=self.general.theme.currentData(),
            rate_limit_cooldown_minutes=self.general.cooldown.value(), auto_resume_after_rate_limit=self.general.auto_resume.isChecked(),
            cookies_mode=self.youtube.mode.currentData(), cookies_file=self.youtube._cookie_file,
            cookies_browser=self.youtube.browser.currentData(), ffmpeg_path=self.tools.ffmpeg.text().strip(),
            mp3gain_path=self.tools.mp3gain.text().strip())

    def save_settings(self) -> None:
        candidate = self.snapshot()
        try:
            settings_module.save(candidate)
        except SettingsError as error:
            self.error.setText(str(error))
            return
        except OSError:
            self.error.setText("Settings could not be saved. Check the data folder permissions.")
            return
        self.result_settings = candidate
        self.accept()

    def test_cookies(self) -> None:
        if self.cookie_worker is not None:
            return
        if not self.test_url:
            self.youtube.test_result.setText("Select a playlist before testing cookies.")
            return
        candidate = self.snapshot()
        if candidate.cookies_mode == "file":
            try:
                with open(candidate.cookies_file, "rb"):
                    pass
            except (OSError, ValueError):
                self.youtube.test_result.setText("Cookie file is missing or unreadable.")
                return
        self.youtube.test_result.setText("Testing cookies…")
        self.youtube.test_button.setEnabled(False)
        self.cookie_worker = CookieTestWorker(self.test_url, candidate)
        self.cookie_worker.signals.completed.connect(self._cookies_tested)
        QThreadPool.globalInstance().start(self.cookie_worker)

    def _cookies_tested(self, success: bool, message: str) -> None:
        self.cookie_worker = None
        self.youtube.test_button.setEnabled(True)
        self.youtube.test_result.setText(message)

    def test_gain(self) -> None:
        if self.gain_worker is not None:
            return
        self.tools.test_result.setText("Reading mp3gain help…")
        self.tools.test_button.setEnabled(False)
        self.gain_worker = GainHelpWorker(self.snapshot())
        self.gain_worker.signals.completed.connect(self._gain_tested)
        QThreadPool.globalInstance().start(self.gain_worker)

    def _gain_tested(self, success: bool, message: str) -> None:
        self.gain_worker = None
        self.tools.test_button.setEnabled(True)
        self.tools.test_result.setText(message)
