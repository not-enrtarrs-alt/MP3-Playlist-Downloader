"""Playlist folder opening and database-only removal actions."""

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

from .. import db


class PlaylistActions:
    def __init__(self, window) -> None:
        self.window = window

    def open_folder(self, playlist_id: int | None) -> None:
        if playlist_id is None:
            return
        connection = db.connect()
        try:
            row = connection.execute("SELECT folder_path FROM playlists WHERE id=?", (playlist_id,)).fetchone()
        finally:
            connection.close()
        if row:
            QDesktopServices.openUrl(QUrl.fromLocalFile(row["folder_path"]))

    def remove_playlist(self, playlist_id: int) -> None:
        if self.window._refresh_worker is not None or self.window.queue_running or self.window.equalizing or self.window.editing:
            return
        answer = QMessageBox.question(self.window, "Remove playlist", "Remove this playlist from the app? Files will remain on disk.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        connection = db.connect()
        try:
            db.remove_playlist(connection, playlist_id)
        finally:
            connection.close()
        self.window.reload_playlists(self.window.selected_id if self.window.selected_id != playlist_id else None)
