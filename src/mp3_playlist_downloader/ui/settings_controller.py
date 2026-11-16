"""Open settings and apply a successfully saved theme immediately."""

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QDialog

from .settings_dialog import SettingsDialog
from .theme import apply_theme, is_dark


class SettingsController(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window

    def open(self, tab: str | None = None) -> None:
        if self.window.queue_running or self.window.equalizing or self.window.editing:
            return
        test_url = self.window.playlist_url.text() if self.window.selected_id is not None else None
        dialog = SettingsDialog(self.window.settings, self.window, test_url=test_url)
        if tab:
            for index in range(dialog.tabs.count()):
                if dialog.tabs.tabText(index) == tab:
                    dialog.tabs.setCurrentIndex(index)
                    break
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.result_settings is None:
            return
        self.window.settings = dialog.result_settings
        app = QApplication.instance()
        apply_theme(app, self.window.settings.theme)
        dark = is_dark(app, self.window.settings.theme)
        self.window.track_model.dark = dark
        self.window.legend.set_dark(dark)
        if self.window.track_model.rows:
            self.window.track_model.dataChanged.emit(self.window.track_model.index(0, 0), self.window.track_model.index(len(self.window.track_model.rows) - 1, 4))
        self.window.update_actions()
