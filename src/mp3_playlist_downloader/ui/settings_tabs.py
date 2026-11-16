"""Widgets for the settings dialog's General, YouTube, Tools and About tabs."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget

from .. import __version__, paths
from ..settings import BROWSERS, Settings


def _combo(options: list[tuple[str, str]], selected: str) -> QComboBox:
    widget = QComboBox()
    for label, value in options:
        widget.addItem(label, value)
    index = widget.findData(selected)
    if index >= 0:
        widget.setCurrentIndex(index)
    return widget


class GeneralTab(QWidget):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        form = QFormLayout(self)
        self.output_root = QLineEdit(settings.output_root)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.output_root, 1)
        row.addWidget(browse)
        form.addRow("Output root", row)
        self.skip = QRadioButton("Skip")
        self.overwrite = QRadioButton("Overwrite")
        self.skip.setChecked(not settings.overwrite_existing)
        self.overwrite.setChecked(settings.overwrite_existing)
        existing = QHBoxLayout()
        existing.addWidget(self.skip)
        existing.addWidget(self.overwrite)
        existing.addStretch()
        form.addRow("Existing tracks", existing)
        self.auto_equalize = QCheckBox("Equalize after each download (irreversible; test on a copy first)")
        self.auto_equalize.setChecked(settings.auto_equalize)
        form.addRow(self.auto_equalize)
        self.confirm_delete = QCheckBox("Confirm before deleting files")
        self.confirm_delete.setChecked(settings.confirm_delete)
        form.addRow(self.confirm_delete)
        self.theme = _combo([("System", "system"), ("Light", "light"), ("Dark", "dark")], settings.theme)
        form.addRow("Theme", self.theme)
        self.cooldown = QSpinBox()
        self.cooldown.setRange(5, 1440)
        self.cooldown.setSuffix(" minutes")
        self.cooldown.setValue(settings.rate_limit_cooldown_minutes)
        form.addRow("Rate-limit cooldown", self.cooldown)
        self.auto_resume = QCheckBox("Automatically resume after rate limits")
        self.auto_resume.setChecked(settings.auto_resume_after_rate_limit)
        form.addRow(self.auto_resume)

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose output root", self.output_root.text())
        if chosen:
            self.output_root.setText(chosen)


class YouTubeTab(QWidget):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._cookie_file = settings.cookies_file
        form = QFormLayout(self)
        self.mode = _combo([("None", "none"), ("cookies.txt", "file"), ("Browser", "browser")], settings.cookies_mode)
        form.addRow("Cookies mode", self.mode)
        self.cookie_label = QLabel("")
        self.cookie_label.setTextFormat(Qt.TextFormat.PlainText)
        browse = QPushButton("Choose file…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.cookie_label, 1)
        row.addWidget(browse)
        form.addRow("Cookie file", row)
        self.browser = _combo([(name.capitalize(), name) for name in sorted(BROWSERS)], settings.cookies_browser)
        form.addRow("Browser", self.browser)
        self.test_button = QPushButton("Test cookies")
        self.test_result = QLabel("")
        self.test_result.setTextFormat(Qt.TextFormat.PlainText)
        self.test_result.setWordWrap(True)
        form.addRow(self.test_button)
        form.addRow(self.test_result)
        self.set_cookie_file(settings.cookies_file)

    def set_cookie_file(self, path: str) -> None:
        self._cookie_file = path
        self.cookie_label.setText(Path(path).name if path else "No file selected")

    def _browse(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, "Choose cookies.txt", "", "Text files (*.txt);;All files (*)")
        if selected:
            self.set_cookie_file(selected)


class ToolsTab(QWidget):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        form = QFormLayout(self)
        try:
            version = importlib.metadata.version("yt-dlp")
        except importlib.metadata.PackageNotFoundError:
            version = "Not installed"
        form.addRow("yt-dlp", QLabel(version))
        self.ffmpeg = QLineEdit(settings.ffmpeg_path)
        self.mp3gain = QLineEdit(settings.mp3gain_path)
        self._tool_row(form, "ffmpeg", self.ffmpeg)
        self._tool_row(form, "mp3gain", self.mp3gain)
        self.test_button = QPushButton("Test mp3gain /?")
        self.test_result = QLabel("")
        self.test_result.setTextFormat(Qt.TextFormat.PlainText)
        self.test_result.setWordWrap(True)
        form.addRow(self.test_button)
        form.addRow(self.test_result)
        for title, filename in (("YouTube setup guide", "SETUP_YOUTUBE.md"), ("mp3gain setup guide", "SETUP_MP3GAIN.md")):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, name=filename: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[3] / "docs" / name))))
            form.addRow(button)

    def _tool_row(self, form: QFormLayout, name: str, field: QLineEdit) -> None:
        row = QHBoxLayout()
        browse, detect = QPushButton("Browse…"), QPushButton("Detect")
        browse.clicked.connect(lambda: self._browse(field))
        detect.clicked.connect(lambda: self._detect(name, field))
        row.addWidget(field, 1)
        row.addWidget(browse)
        row.addWidget(detect)
        form.addRow(name, row)

    def _browse(self, field: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose tool", "", "Programs (*.exe);;All files (*)")
        if path:
            field.setText(path)

    def _detect(self, name: str, field: QLineEdit) -> None:
        found = paths.find_tool(name, field.text())
        if found:
            field.setText(found)
            self.test_result.setText(f"{name} found.")
        else:
            self.test_result.setText(f"{name} not found.")


class AboutTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"MP3 Playlist Downloader {__version__}"))
        for label, directory in (("Open data folder", paths.data_dir()), ("Open logs", paths.log_dir())):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, path=directory: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
            layout.addWidget(button)
        layout.addStretch()
