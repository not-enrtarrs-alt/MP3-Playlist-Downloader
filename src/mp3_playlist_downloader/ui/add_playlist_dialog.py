"""Playlist URL entry and cancellable background metadata fetch."""

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QVBoxLayout

from ..settings import Settings
from ..youtube.parse import normalize_playlist_url
from .workers import PlaylistWorker


class AddPlaylistDialog(QDialog):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.playlist_id: int | None = None
        self.worker: PlaylistWorker | None = None
        self.setWindowTitle("Add playlist")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Enter a YouTube playlist URL:"))
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://www.youtube.com/playlist?list=…")
        layout.addWidget(self.url)
        layout.addWidget(QLabel("Single videos and endless mixes are not supported."))
        self.message = QLabel("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.spinner = QProgressBar()
        self.spinner.setRange(0, 0)
        self.spinner.hide()
        layout.addWidget(self.spinner)
        buttons = QHBoxLayout()
        self.add_button = QPushButton("Add")
        self.cancel_button = QPushButton("Cancel")
        buttons.addStretch()
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)
        self.add_button.clicked.connect(self.start)
        self.url.returnPressed.connect(self.start)
        self.cancel_button.clicked.connect(self.reject)

    def start(self) -> None:
        if self.worker is not None:
            return
        try:
            url = normalize_playlist_url(self.url.text())
        except ValueError as error:
            self.message.setText(str(error))
            return
        self.message.setText("Reading playlist…")
        self.spinner.show()
        self.add_button.setEnabled(False)
        self.url.setEnabled(False)
        self.worker = PlaylistWorker(self.settings, url=url)
        self.worker.signals.completed.connect(self._completed)
        self.worker.signals.error.connect(self._error)
        self.worker.signals.finished.connect(self._finished)
        QThreadPool.globalInstance().start(self.worker)

    def _completed(self, playlist_id: int, added: bool) -> None:
        self.playlist_id = playlist_id
        self.accept()

    def _error(self, message: str) -> None:
        self.message.setText(message)

    def _finished(self) -> None:
        self.worker = None
        self.spinner.hide()
        self.add_button.setEnabled(True)
        self.url.setEnabled(True)

    def reject(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
        super().reject()
