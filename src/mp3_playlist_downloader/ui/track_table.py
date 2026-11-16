"""Track table and tri-state select-all header."""

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPalette
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QStyle, QStyleOptionButton, QStyledItemDelegate, QTableView

from .track_model import TrackModel


class CheckHeader(QHeaderView):
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setSectionsClickable(True)
        self.sectionClicked.connect(self._clicked)

    def _clicked(self, section: int) -> None:
        model = self.model()
        if section == 0 and isinstance(model, TrackModel):
            model.set_all(model.check_state() != Qt.CheckState.Checked)

    def paintSection(self, painter, rect: QRect, logical_index: int) -> None:
        super().paintSection(painter, rect, logical_index)
        model = self.model()
        if logical_index != 0 or not isinstance(model, TrackModel):
            return
        option = QStyleOptionButton()
        option.rect = QRect(rect.center().x() - 7, rect.center().y() - 7, 14, 14)
        option.state = QStyle.StateFlag.State_Enabled
        state = model.check_state()
        option.state |= {Qt.CheckState.Checked: QStyle.StateFlag.State_On, Qt.CheckState.Unchecked: QStyle.StateFlag.State_Off, Qt.CheckState.PartiallyChecked: QStyle.StateFlag.State_NoChange}[state]
        self.style().drawControl(QStyle.ControlElement.CE_CheckBox, option, painter, self)


class StatusDelegate(QStyledItemDelegate):
    """Keep the model's status color visible on a selected row."""

    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        foreground = index.data(Qt.ItemDataRole.ForegroundRole)
        if isinstance(foreground, QColor):
            option.palette.setColor(QPalette.ColorRole.HighlightedText, foreground)


class TrackTable(QTableView):
    delete_requested = Signal()

    def __init__(self, model: TrackModel, parent=None) -> None:
        super().__init__(parent)
        self.setHorizontalHeader(CheckHeader(self))
        self.setModel(model)
        self.setItemDelegate(StatusDelegate(self))
        model.selection_changed.connect(self.horizontalHeader().viewport().update)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSortingEnabled(False)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(30)
        self.setColumnWidth(0, 36)
        self.setColumnWidth(1, 50)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.setColumnWidth(3, 75)
        self.setColumnWidth(4, 190)

    def keyPressEvent(self, event) -> None:
        model = self.model()
        if event.matches(QKeySequence.StandardKey.SelectAll):
            model.set_all(True)
        elif event.key() == Qt.Key.Key_Delete:
            self.delete_requested.emit()
        elif event.key() == Qt.Key.Key_Space and self.currentIndex().isValid():
            index = model.index(self.currentIndex().row(), 0)
            state = index.data(Qt.ItemDataRole.CheckStateRole)
            model.setData(index, Qt.CheckState.Unchecked if state == Qt.CheckState.Checked else Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
        else:
            super().keyPressEvent(event)
