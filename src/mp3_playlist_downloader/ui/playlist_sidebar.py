"""Playlist sidebar operating exclusively on cached database rows."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QMenu, QPushButton, QVBoxLayout, QWidget


class PlaylistSidebar(QWidget):
    selected = Signal(int)
    add_requested = Signal()
    refresh_requested = Signal(int)
    open_requested = Signal(int)
    remove_requested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Playlists"))
        self.list = QListWidget()
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.currentItemChanged.connect(self._select)
        self.list.customContextMenuRequested.connect(self._menu)
        layout.addWidget(self.list, 1)
        self.add_button = QPushButton("+ Add playlist")
        self.add_button.clicked.connect(self.add_requested)
        layout.addWidget(self.add_button)
        self.busy = False

    def populate(self, playlists, selected_id: int | None = None) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        selection = None
        for playlist in playlists:
            item = QListWidgetItem(f"{playlist['title']}\n{playlist['track_count']} tracks · {playlist['downloaded_count']} downloaded")
            item.setData(Qt.ItemDataRole.UserRole, playlist["id"])
            item.setToolTip(playlist["url"])
            self.list.addItem(item)
            if playlist["id"] == selected_id:
                selection = item
        if selection is not None:
            self.list.setCurrentItem(selection)
        self.list.blockSignals(False)

    def _select(self, current, previous) -> None:
        if current is not None:
            self.selected.emit(current.data(Qt.ItemDataRole.UserRole))

    def _menu(self, point) -> None:
        item = self.list.itemAt(point)
        if item is None:
            return
        playlist_id = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        refresh = menu.addAction("Refresh")
        open_folder = menu.addAction("Open folder")
        remove = menu.addAction("Remove playlist")
        refresh.setEnabled(not self.busy)
        remove.setEnabled(not self.busy)
        choice = menu.exec(self.list.viewport().mapToGlobal(point))
        if choice == refresh:
            self.refresh_requested.emit(playlist_id)
        elif choice == open_folder:
            self.open_requested.emit(playlist_id)
        elif choice == remove:
            self.remove_requested.emit(playlist_id)

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.add_button.setEnabled(not busy)
