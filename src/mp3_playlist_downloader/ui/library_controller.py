"""Coordinate folder scans and explicit file actions with the main window."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThreadPool
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

from .. import equalizer
from .explorer import reveal_file
from .extra_files_dialog import ExtraFilesDialog
from .library_workers import ActionWorker, ScanWorker


def _execute_menu(menu: QMenu, global_point):
    """Run the native menu; wrapper permits deterministic UI testing."""
    return menu.exec(global_point)


class LibraryController(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.scans: dict[int, ScanWorker] = {}
        self.action: ActionWorker | None = None
        self.reviewing = False

    def scan(self, playlist_id: int) -> None:
        if playlist_id in self.scans or self.window.queue_running or self.window.equalizing or self.window.editing:
            return
        worker = ScanWorker(playlist_id)
        self.scans[playlist_id] = worker
        worker.signals.completed.connect(self._scan_finished)
        self.window.update_actions()
        QThreadPool.globalInstance().start(worker)

    def _scan_finished(self, playlist_id: int, result, error: str) -> None:
        self.scans.pop(playlist_id, None)
        self.window.update_actions()
        if self.window.selected_id != playlist_id:
            return
        if error:
            self.window.warning_banner.setText(error)
            self.window.warning_banner.show()
            return
        self.window.select_playlist(playlist_id, scan=False, preserve_selection=True)
        self.window.set_extra_banner(result.pending_count)
        if result.new_extra_ids and not self.window.queue_running and not self.window.equalizing and not self.window.editing:
            self.review()

    def review(self) -> None:
        if self.window.selected_id is None or self.window.queue_running or self.window.equalizing or self.window.editing or self.reviewing:
            return
        playlist_id = self.window.selected_id
        dialog = ExtraFilesDialog(playlist_id, self.window)
        self.reviewing = True
        self.window.update_actions()
        try:
            dialog.exec()
        finally:
            self.reviewing = False
            self.window.update_actions()
        if self.window.selected_id == playlist_id:
            self.window.select_playlist(playlist_id, scan=False, preserve_selection=True)
            self.window.set_extra_banner(sum(bool(row.get("_extra")) and row.get("disposition") == "pending" for row in self.window.track_model.rows))

    def delete_selected(self) -> None:
        if self.window.queue_running or self.window.equalizing or self.window.editing or self.action is not None:
            return
        rows = [self.window.track_model.rows[index] for index in sorted(self.window.track_model.checked)]
        self._delete_rows(rows)

    def _delete_rows(self, rows) -> None:
        if self.window.queue_running or self.window.equalizing or self.window.editing or self.action is not None:
            return
        if not rows:
            return
        if self.window.settings.confirm_delete:
            answer = QMessageBox.question(self.window, "Delete files", f"Move {len(rows)} selected item(s) to the Recycle Bin?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._run_actions([("delete_extra" if row.get("_extra") else "delete_track", row["id"]) for row in rows])

    def show_context_menu(self, point) -> None:
        index = self.window.track_table.indexAt(point)
        if not index.isValid():
            return
        row = self.window.track_model.rows[index.row()]
        menu = QMenu(self.window.track_table)
        keep = menu.addAction("Keep file") if row.get("_extra") else None
        gain = None if row.get("_extra") else menu.addAction("Equalize now")
        link = None if row.get("_extra") else menu.addAction("Point to MP3 file…")
        rename = None if row.get("_extra") else menu.addAction("Rename track…")
        redownload = None if row.get("_extra") else menu.addAction("Re-download")
        busy = self.window.queue_running or self.window.equalizing or self.window.editing or self.action is not None
        if link:
            link.setEnabled(not busy and not self.scans)
        if rename:
            rename.setEnabled(not busy and not self.scans and row.get("download_state") != "downloading")
        if gain:
            gain.setEnabled(bool(row.get("downloaded") and not row.get("equalized") and row.get("file_path") and not busy and equalizer.discover(self.window.settings)))
        if redownload:
            redownload.setEnabled(bool(row.get("in_playlist", 1) and not row.get("unavailable") and not busy and not self.scans))
        reveal = menu.addAction("Open in Explorer")
        reveal.setEnabled(bool(row.get("file_path")))
        copy_url = None if row.get("_extra") else menu.addAction("Copy YouTube URL")
        delete = menu.addAction("Delete file" if row.get("_extra") else "Delete from disk")
        if keep:
            keep.setEnabled(not busy)
        delete.setEnabled(not busy)
        choice = _execute_menu(menu, self.window.track_table.viewport().mapToGlobal(point))
        if choice is None:
            return
        if choice == keep:
            self._run_actions([("keep_extra", row["id"])])
        elif choice == gain:
            self.window.equalizer_controller.start([row["id"]])
        elif choice == link:
            self.window.edit_controller.point_to_file(row["id"])
        elif choice == rename:
            self.window.edit_controller.rename_track(row["id"])
        elif choice == redownload:
            self.window.queue_controller.redownload(row["id"])
        elif choice == reveal:
            reveal_file(row["file_path"])
        elif choice == copy_url:
            QApplication.clipboard().setText("https://www.youtube.com/watch?v=" + row["video_id"])
        elif choice == delete:
            self._delete_rows([row])

    def open_row(self, index) -> None:
        row = self.window.track_model.rows[index.row()]
        if row.get("file_path"):
            reveal_file(row["file_path"])

    def _run_actions(self, actions: list[tuple[str, int]]) -> None:
        self.action = ActionWorker(actions)
        self.action.signals.completed.connect(self._action_finished)
        self.window.update_actions()
        QThreadPool.globalInstance().start(self.action)

    def _action_finished(self, succeeded: int, failed: int) -> None:
        self.action = None
        if failed:
            QMessageBox.warning(self.window, "File action", f"{failed} item(s) could not be processed; their database state was not changed.")
        if self.window.selected_id is not None:
            self.window.select_playlist(self.window.selected_id, scan=False)
            self.scan(self.window.selected_id)
        self.window.update_actions()
