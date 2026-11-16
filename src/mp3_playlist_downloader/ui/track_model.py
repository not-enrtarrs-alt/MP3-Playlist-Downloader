"""Cached track model with accessible state text and independent checkboxes."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QFont

from ..youtube.parse import title_and_artist

LIGHT = {"green": "#1B7F3B", "blue": "#1565C0", "red": "#C62828", "yellow": "#8A6100", "grey": "#5F6368"}
DARK = {"green": "#4CAF50", "blue": "#64B5F6", "red": "#EF5350", "yellow": "#FFD54F", "grey": "#9CA3AF"}


def row_state(row: dict[str, Any]) -> tuple[str, str]:
    if row.get("_extra"):
        return ("Extra file · kept" if row.get("disposition") == "kept" else "Extra file", "yellow")
    if row.get("downloaded"):
        return ("Downloaded · equalized", "green") if row.get("equalized") else ("Downloaded", "blue")
    if not row.get("in_playlist", 1):
        return "Removed from playlist", "grey"
    if row.get("unavailable"):
        return "Unavailable", "grey"
    if row.get("download_state") == "failed":
        return "Failed", "red"
    return "Not downloaded", "red"


class TrackModel(QAbstractTableModel):
    selection_changed = Signal()
    HEADERS = ("", "#", "Title", "Duration", "State")

    def __init__(self, parent=None, dark: bool = False) -> None:
        super().__init__(parent)
        self.rows: list[dict[str, Any]] = []
        self.checked: set[int] = set()
        self.dark = dark

    def set_rows(self, rows: list[dict[str, Any]], preserve_selection: bool = False) -> None:
        keys = {(bool(self.rows[index].get("_extra")), self.rows[index].get("id")) for index in self.checked} if preserve_selection else set()
        self.beginResetModel()
        self.rows = [dict(row) for row in rows]
        self.checked = {index for index, row in enumerate(self.rows) if (bool(row.get("_extra")), row.get("id")) in keys}
        self.endResetModel()
        self.selection_changed.emit()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row, column = self.rows[index.row()], index.column()
        state, color = row_state(row)
        if role == Qt.ItemDataRole.CheckStateRole and column == 0:
            return Qt.CheckState.Checked if index.row() in self.checked else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.ForegroundRole and column in (2, 4):
            return QColor((DARK if self.dark else LIGHT)[color])
        if role == Qt.ItemDataRole.FontRole and column == 2 and not row.get("_extra") and not row.get("in_playlist", 1):
            font = QFont()
            font.setItalic(True)
            return font
        if role == Qt.ItemDataRole.ToolTipRole:
            lines = [row.get("title") or row.get("file_name", "")]
            if row.get("file_path"):
                lines.append(str(row["file_path"]))
            if row.get("video_id"):
                lines.append("https://www.youtube.com/watch?v=" + row["video_id"])
            if row.get("last_error"):
                lines.append(str(row["last_error"])[:500])
            if row.get("downloaded") and (not row.get("in_playlist", 1) or row.get("unavailable")):
                lines.append("Removed from playlist" if not row.get("in_playlist", 1) else "Unavailable")
            return "\n".join(lines)
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 1:
                return "" if row.get("_extra") else str(row.get("position", 0) + 1)
            if column == 2:
                if row.get("_extra"):
                    return row.get("file_name", "")
                title, _ = title_and_artist(row.get("title", ""), row.get("uploader"), row.get("custom_title"))
                if row.get("is_topic"):
                    title += "  [Topic]"
                if not row.get("in_playlist", 1):
                    title += "  [Removed]"
                elif row.get("unavailable") and row.get("downloaded"):
                    title += "  [Unavailable]"
                return title
            if column == 3:
                seconds = row.get("duration_seconds")
                return f"{seconds // 60}:{seconds % 60:02d}" if isinstance(seconds, int) else ""
            if column == 4:
                return ("⚠ " if state == "Failed" else "● ") + state
        return None

    def flags(self, index: QModelIndex):
        flags = super().flags(index)
        return flags | Qt.ItemFlag.ItemIsUserCheckable if index.isValid() and index.column() == 0 else flags

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or index.column() != 0 or role != Qt.ItemDataRole.CheckStateRole:
            return False
        if value == Qt.CheckState.Checked or value == Qt.CheckState.Checked.value:
            self.checked.add(index.row())
        else:
            self.checked.discard(index.row())
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        self.selection_changed.emit()
        return True

    def set_all(self, checked: bool) -> None:
        self.checked = set(range(len(self.rows))) if checked else set()
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, 0), [Qt.ItemDataRole.CheckStateRole])
        self.selection_changed.emit()

    def check_state(self) -> Qt.CheckState:
        if not self.checked:
            return Qt.CheckState.Unchecked
        if len(self.checked) == len(self.rows):
            return Qt.CheckState.Checked
        return Qt.CheckState.PartiallyChecked
