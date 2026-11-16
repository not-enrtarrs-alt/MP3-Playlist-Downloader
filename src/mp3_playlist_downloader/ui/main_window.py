"""Main window with cached playlist selection and threaded refresh."""

from __future__ import annotations

import logging

from PySide6.QtCore import QByteArray, QThreadPool, Qt
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget

from .. import db, equalizer, library
from ..settings import Settings, SettingsError, save
from .add_playlist_dialog import AddPlaylistDialog
from .edit_controller import EditController
from .equalizer_controller import EqualizerController
from .legend_panel import LegendPanel
from .library_controller import LibraryController
from .playlist_actions import PlaylistActions
from .playlist_sidebar import PlaylistSidebar
from .queue_controller import QueueController
from .settings_controller import SettingsController
from .track_model import TrackModel
from .track_table import TrackTable
from .theme import is_dark
from .workers import PlaylistWorker

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, warnings: list[str] | None = None) -> None:
        super().__init__()
        self.settings = settings
        self.selected_id: int | None = None
        self._refresh_worker: PlaylistWorker | None = None
        self._database_ready = False
        self.queue_running = False
        self.equalizing = False
        self.editing = False
        self.playlist_actions = PlaylistActions(self)
        self.setWindowTitle("MP3 Playlist Downloader")
        self.setMinimumSize(1000, 620)
        self.resize(1280, 800)
        if settings.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(settings.window_geometry.encode("ascii", errors="ignore")))
        content = QWidget()
        layout = QVBoxLayout(content)
        self.warning_banner = QLabel("\n".join(warnings or []))
        self.warning_banner.setWordWrap(True)
        self.warning_banner.setStyleSheet("background: #fff0bd; color: #593f00; padding: 8px;")
        self.warning_banner.setVisible(bool(warnings))
        layout.addWidget(self.warning_banner)
        extras_bar = QHBoxLayout()
        self.extras_message = QLabel("")
        self.extras_review = QPushButton("Review")
        extras_bar.addWidget(self.extras_message)
        extras_bar.addWidget(self.extras_review)
        extras_bar.addStretch()
        self.extras_message.hide()
        self.extras_review.hide()
        layout.addLayout(extras_bar)

        header = QHBoxLayout()
        self.settings_button = QPushButton("⚙ Settings")
        header.addWidget(self.settings_button)
        header.addWidget(QLabel("MP3 Playlist Downloader"))
        header.addStretch()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_current)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.sidebar = PlaylistSidebar()
        self.sidebar.selected.connect(self.select_playlist)
        self.sidebar.add_requested.connect(self.add_playlist)
        self.sidebar.refresh_requested.connect(self.refresh_playlist)
        self.sidebar.open_requested.connect(self.playlist_actions.open_folder)
        self.sidebar.remove_requested.connect(self.playlist_actions.remove_playlist)
        splitter.addWidget(self.sidebar)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        self.playlist_title = QLabel("")
        self.playlist_url = QLabel("")
        self.playlist_title.setTextFormat(Qt.TextFormat.PlainText)
        self.playlist_url.setTextFormat(Qt.TextFormat.PlainText)
        self.playlist_url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.folder_label = QLabel("")
        self.folder_label.setTextFormat(Qt.TextFormat.PlainText)
        self.folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.open_button = QPushButton("Open folder")
        self.open_button.clicked.connect(lambda: self.playlist_actions.open_folder(self.selected_id))
        center_layout.addWidget(self.playlist_title)
        center_layout.addWidget(self.playlist_url)
        center_layout.addWidget(self.folder_label)
        center_layout.addWidget(self.open_button)
        self.album_banner = QLabel('<a href="update">Album tags out of date — Update</a>')
        self.album_banner.hide()
        center_layout.addWidget(self.album_banner)
        toolbar = QHBoxLayout()
        self.equalize_button = QPushButton("Equalize selected")
        self.select_all_button = QPushButton("Select all")
        self.unselect_all_button = QPushButton("Unselect all")
        self.download_button = QPushButton("Download missing")
        self.delete_button = QPushButton("Delete selected")
        for button in (self.equalize_button, self.select_all_button, self.unselect_all_button, self.download_button, self.delete_button):
            toolbar.addWidget(button)
        for button in (self.equalize_button, self.download_button, self.delete_button):
            button.setEnabled(False)
            button.setToolTip("This action is not implemented yet.")
        center_layout.addLayout(toolbar)
        dark = is_dark(QApplication.instance(), settings.theme)
        self.track_model = TrackModel(self, dark=dark)
        self.track_table = TrackTable(self.track_model)
        self.track_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.track_model.selection_changed.connect(self._update_counts)
        self.select_all_button.clicked.connect(lambda: self.track_model.set_all(True))
        self.unselect_all_button.clicked.connect(lambda: self.track_model.set_all(False))
        self.empty_message = QLabel("No playlists yet")
        self.empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(self.empty_message, 1)
        self.empty_add = QPushButton("+ Add playlist")
        self.empty_add.clicked.connect(self.add_playlist)
        center_layout.addWidget(self.empty_add, alignment=Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(self.track_table, 1)
        splitter.addWidget(center)
        self.legend = LegendPanel(dark=dark)
        splitter.addWidget(self.legend)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 820, 200])
        layout.addWidget(splitter, 1)
        self.library_controller = LibraryController(self)
        self.queue_controller = QueueController(self, layout)
        self.equalizer_controller = EqualizerController(self)
        self.edit_controller = EditController(self)
        self.settings_controller = SettingsController(self)
        self.log_button = QPushButton("Show log")
        self.log_button.setCheckable(True)
        self.log_drawer = QPlainTextEdit()
        self.log_drawer.setReadOnly(True)
        self.log_drawer.setMaximumBlockCount(1000)
        self.log_drawer.hide()
        self.log_button.toggled.connect(self.log_drawer.setVisible)
        self.log_button.toggled.connect(lambda shown: self.log_button.setText("Hide log" if shown else "Show log"))
        layout.addWidget(self.log_button)
        layout.addWidget(self.log_drawer)
        self.setCentralWidget(content)
        self.statusBar().showMessage("Ready")
        self.extras_review.clicked.connect(self.library_controller.review)
        self.delete_button.clicked.connect(self.library_controller.delete_selected)
        self.track_table.delete_requested.connect(self.library_controller.delete_selected)
        self.track_table.customContextMenuRequested.connect(self.library_controller.show_context_menu)
        self.track_table.doubleClicked.connect(self.library_controller.open_row)
        self.download_button.clicked.connect(self.queue_controller.start_missing)
        self.equalize_button.clicked.connect(lambda: self.equalizer_controller.start())
        self.queue_controller.cancel_button.clicked.connect(self.equalizer_controller.cancel)
        self.queue_controller.cancel_button.clicked.connect(self.edit_controller.cancel)
        self.album_banner.linkActivated.connect(lambda _link: self.edit_controller.sync_album())
        self.settings_button.clicked.connect(self.settings_controller.open)
        self.reload_playlists()
        self.queue_controller._recover()

    def reload_playlists(self, selected_id: int | None = None) -> None:
        connection = db.connect()
        try:
            if not self._database_ready:
                db.initialize(connection)
                self._database_ready = True
            playlists = db.list_playlists(connection)
        finally:
            connection.close()
        ids = [row["id"] for row in playlists]
        if selected_id not in ids:
            selected_id = ids[0] if ids else None
        self.sidebar.populate(playlists, selected_id)
        if selected_id is None:
            self.selected_id = None
            self.track_model.set_rows([])
            self.playlist_title.setText("")
            self.playlist_url.setText("")
            self.folder_label.setText("")
            self.album_banner.hide()
            self.set_extra_banner(0)
            self.empty_message.setText("No playlists yet")
            self.empty_message.show()
            self.empty_add.show()
            self.track_table.hide()
            self.open_button.setEnabled(False)
            self.refresh_button.setEnabled(False)
        else:
            self.select_playlist(selected_id)

    def select_playlist(self, playlist_id: int, scan: bool = True, preserve_selection: bool = False) -> None:
        """Read only cached SQLite data; never contact YouTube on selection."""
        connection = db.connect()
        try:
            row = connection.execute("SELECT * FROM playlists WHERE id=?", (playlist_id,)).fetchone()
            videos = db.list_videos(connection, playlist_id)
            extras = library.list_extras(connection, playlist_id)
        finally:
            connection.close()
        if row is None:
            return
        self.selected_id = playlist_id
        self.playlist_title.setText(row["title"])
        self.playlist_url.setText(row["url"])
        self.folder_label.setText(row["folder_path"])
        self.album_banner.setVisible(bool(row["album_sync_pending"]))
        rows = [dict(video) for video in videos] + [{**dict(extra), "_extra": True} for extra in extras]
        self.track_model.set_rows(rows, preserve_selection=preserve_selection)
        self.empty_add.hide()
        self.empty_message.setText("This playlist has no tracks. Refresh it.")
        self.empty_message.setVisible(not rows)
        self.track_table.setVisible(bool(rows))
        self.open_button.setEnabled(True)
        self.refresh_button.setEnabled(self._refresh_worker is None and not self.queue_running and not self.equalizing and not self.editing)
        self.set_extra_banner(sum(extra["disposition"] == "pending" for extra in extras))
        if scan:
            self.library_controller.scan(playlist_id)

    def _update_counts(self) -> None:
        self.legend.update_stats(self.track_model.rows, len(self.track_model.checked))
        enabled = bool(self.track_model.rows)
        self.select_all_button.setEnabled(enabled)
        self.unselect_all_button.setEnabled(enabled)
        self.update_actions()

    def set_extra_banner(self, count: int) -> None:
        self.extras_message.setText(f"{count} additional file(s) found")
        self.extras_message.setVisible(count > 0)
        self.extras_review.setVisible(count > 0)

    def update_actions(self) -> None:
        busy = self.queue_running or self.equalizing or self.editing or (hasattr(self, "library_controller") and self.library_controller.action is not None)
        self.delete_button.setEnabled(bool(self.track_model.checked) and not busy)
        self.delete_button.setToolTip(f"{len(self.track_model.checked)} selected · delete via Recycle Bin")
        blocked = busy or bool(self.library_controller.scans) or self.library_controller.reviewing or self._refresh_worker is not None
        if hasattr(self, "queue_controller"):
            blocked = blocked or self.queue_controller.recovery is not None
        eligible = any(not row.get("_extra") and row.get("in_playlist", 1) and not row.get("unavailable") and (not row.get("downloaded") or self.settings.overwrite_existing) and row.get("download_state") not in ("downloading", "queued") for row in self.track_model.rows)
        pending = hasattr(self, "queue_controller") and self.queue_controller.pending > 0
        self.download_button.setEnabled(bool((eligible or pending) and not blocked))
        self.download_button.setToolTip("Download missing tracks or resume pending downloads." if not blocked else "Wait for the current operation to finish.")
        selected = self.equalizer_controller.eligible() if hasattr(self, "equalizer_controller") else []
        gain_available = bool(equalizer.discover(self.settings))
        self.equalize_button.setEnabled(bool(selected) and gain_available and not blocked)
        self.equalize_button.setToolTip(equalizer.MISSING_MESSAGE if not gain_available else f"{len(self.track_model.checked)} selected · {len(selected)} eligible")
        self.settings_button.setEnabled(not self.queue_running and not self.equalizing and not self.editing)

    def add_playlist(self) -> None:
        if self._refresh_worker is not None or self.queue_running or self.equalizing or self.editing:
            return
        dialog = AddPlaylistDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.playlist_id is not None:
            self.reload_playlists(dialog.playlist_id)

    def refresh_current(self) -> None:
        if self.selected_id is not None:
            self.refresh_playlist(self.selected_id)

    def refresh_playlist(self, playlist_id: int) -> None:
        if self._refresh_worker is not None or self.queue_running or self.equalizing or self.editing:
            return
        self._refresh_worker = PlaylistWorker(self.settings, playlist_id=playlist_id)
        self._refresh_worker.signals.completed.connect(lambda _id, _added: self.reload_playlists(self.selected_id))
        self._refresh_worker.signals.error.connect(self._show_error)
        self._refresh_worker.signals.finished.connect(self._refresh_finished)
        self.sidebar.set_busy(True)
        self.refresh_button.setEnabled(False)
        self.empty_add.setEnabled(False)
        self.statusBar().showMessage("Reading playlist…")
        self.update_actions()
        QThreadPool.globalInstance().start(self._refresh_worker)

    def _refresh_finished(self) -> None:
        self._refresh_worker = None
        self.sidebar.set_busy(False)
        self.empty_add.setEnabled(True)
        self.refresh_button.setEnabled(self.selected_id is not None)
        self.statusBar().showMessage("Ready")
        self.update_actions()

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "Playlist error", message)

    def append_log(self, line: str) -> None:
        self.log_drawer.appendPlainText(line)

    def closeEvent(self, event) -> None:
        if self.editing:
            answer = QMessageBox.question(self, "Close during file operation", "Cancel after the current file and close?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                self.edit_controller.close_after_cancel = True
                self.edit_controller.cancel()
            event.ignore()
            return
        if self.equalizing:
            answer = QMessageBox.question(self, "Close during equalization", "Cancel after the current file and close? Gain changes cannot be undone.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                self.equalizer_controller.close_after_cancel = True
                self.equalizer_controller.cancel()
            event.ignore()
            return
        if self.queue_running:
            answer = QMessageBox.question(self, "Close during download", "Cancel the download and close? Remaining tracks will stay queued.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                self.queue_controller.close_after_cancel = True
                self.queue_controller.cancel()
            event.ignore()
            return
        if self._refresh_worker is not None:
            self._refresh_worker.cancel()
        self.settings.window_geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
        try:
            save(self.settings)
        except (OSError, SettingsError):
            logger.warning("Window geometry could not be saved.")
        super().closeEvent(event)
