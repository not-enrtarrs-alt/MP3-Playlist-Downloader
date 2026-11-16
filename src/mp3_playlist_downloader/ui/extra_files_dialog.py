"""Explicit decisions for MP3 files not tracked by a playlist."""

from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout

from .. import db, library
from .library_workers import ActionWorker


class ExtraFilesDialog(QDialog):
    def __init__(self, playlist_id: int, parent=None) -> None:
        super().__init__(parent)
        self.playlist_id = playlist_id
        self.worker: ActionWorker | None = None
        self.setWindowTitle("Additional files found")
        self.resize(560, 360)
        layout = QVBoxLayout(self)
        text = QLabel("These MP3 files are in the playlist folder but are not tracked by the app.")
        text.setWordWrap(True)
        layout.addWidget(text)
        self.list = QListWidget()
        layout.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        self.keep_button = QPushButton("Keep selected")
        self.delete_button = QPushButton("Delete selected")
        self.later_button = QPushButton("Decide later")
        for button in (self.keep_button, self.delete_button, self.later_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.keep_button.clicked.connect(lambda: self._start("keep_extra"))
        self.delete_button.clicked.connect(lambda: self._start("delete_extra"))
        self.later_button.clicked.connect(self.reject)
        self.reload()

    def reload(self) -> None:
        self.list.clear()
        connection = db.connect()
        try:
            extras = library.list_extras(connection, self.playlist_id)
        finally:
            connection.close()
        for row in extras:
            if row["disposition"] != "pending":
                continue
            size = row["size_bytes"] or 0
            item = QListWidgetItem(f"{row['file_name']}  ·  {size:,} bytes")
            item.setData(Qt.ItemDataRole.UserRole, row["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.list.addItem(item)

    def _start(self, action: str) -> None:
        if self.worker is not None:
            return
        selected = [self.list.item(index).data(Qt.ItemDataRole.UserRole) for index in range(self.list.count()) if self.list.item(index).checkState() == Qt.CheckState.Checked]
        if not selected:
            return
        if action == "delete_extra":
            answer = QMessageBox.question(self, "Delete files", f"Move {len(selected)} selected file(s) to the Recycle Bin?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.worker = ActionWorker([(action, row_id) for row_id in selected])
        self.worker.signals.completed.connect(self._finished)
        for button in (self.keep_button, self.delete_button, self.later_button):
            button.setEnabled(False)
        QThreadPool.globalInstance().start(self.worker)

    def _finished(self, succeeded: int, failed: int) -> None:
        self.worker = None
        for button in (self.keep_button, self.delete_button, self.later_button):
            button.setEnabled(True)
        if failed:
            QMessageBox.warning(self, "File action", f"{failed} file(s) could not be processed; nothing was permanently deleted.")
        self.reload()
        if not self.list.count():
            self.accept()

    def reject(self) -> None:
        if self.worker is None:
            super().reject()
