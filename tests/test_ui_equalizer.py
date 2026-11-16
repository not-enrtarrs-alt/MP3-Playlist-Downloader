from dataclasses import replace
import threading

from PySide6.QtWidgets import QDialog, QMessageBox

from mp3_playlist_downloader import db, equalizer
from mp3_playlist_downloader.models import PlaylistMetadata, VideoMetadata
from mp3_playlist_downloader.settings import Settings
from mp3_playlist_downloader.ui.main_window import MainWindow


def seed(monkeypatch, tmp_path):
    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    connection = db.connect()
    db.initialize(connection)
    pid, _ = db.add_playlist(connection, "url", PlaylistMetadata("Playlist", (VideoMetadata("aaaaaaaaaaa", "First"), VideoMetadata("bbbbbbbbbbb", "Second", position=1))), tmp_path / "music")
    for index, row in enumerate(db.list_videos(connection, pid)):
        path = tmp_path / "music" / "Playlist" / f"{index}.mp3"
        path.write_bytes(b"audio")
        with connection:
            connection.execute("UPDATE videos SET downloaded=1,file_path=?,file_size=5 WHERE id=?", (str(path), row["id"]))
    connection.close()
    return pid


def test_selected_equalization_continues_after_failure(qtbot, monkeypatch, tmp_path):
    pid = seed(monkeypatch, tmp_path)
    monkeypatch.setattr(equalizer, "discover", lambda settings: "fake")
    def apply(path, settings):
        if path.name == "0.mp3":
            raise equalizer.EqualizerError("mp3gain failed")
    monkeypatch.setattr(equalizer, "apply", apply)
    window = MainWindow(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.queue_controller.recovery is None and not window.library_controller.scans, timeout=5000)
    window.track_model.set_all(True)
    assert window.equalize_button.isEnabled()
    window.equalize_button.click()
    qtbot.waitUntil(lambda: not window.equalizing and not window.library_controller.scans, timeout=5000)
    connection = db.connect()
    rows = db.list_videos(connection, pid)
    connection.close()
    assert [row["equalized"] for row in rows] == [0, 1]
    assert rows[0]["error_kind"] == "equalize"
    assert "1 succeeded, 1 failed" in window.queue_controller.progress_label.text()
    assert window.queue_controller.progress_bar.value() == 100
    window.close()


def test_missing_equalizer_disables_button_and_explains(qtbot, monkeypatch, tmp_path):
    seed(monkeypatch, tmp_path)
    monkeypatch.setattr(equalizer, "discover", lambda settings: None)
    window = MainWindow(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.queue_controller.recovery is None and not window.library_controller.scans, timeout=5000)
    window.track_model.set_all(True)
    assert not window.equalize_button.isEnabled()
    assert "mp3gain not found" in window.equalize_button.toolTip()
    messages = []
    monkeypatch.setattr(window.equalizer_controller, "show_missing", lambda: messages.append(equalizer.MISSING_MESSAGE))
    window.equalizer_controller.start()
    assert messages and not window.equalizing
    window.close()


def test_closing_equalization_waits_for_current_file(qtbot, monkeypatch, tmp_path):
    pid = seed(monkeypatch, tmp_path)
    monkeypatch.setattr(equalizer, "discover", lambda settings: "fake")
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    entered, release = threading.Event(), threading.Event()
    def apply(path, settings):
        entered.set()
        release.wait(5)
    monkeypatch.setattr(equalizer, "apply", apply)
    window = MainWindow(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.queue_controller.recovery is None and not window.library_controller.scans, timeout=5000)
    window.track_model.set_all(True)
    window.equalize_button.click()
    qtbot.waitUntil(entered.is_set, timeout=5000)
    assert not window.download_button.isEnabled() and not window.delete_button.isEnabled()
    window.close()
    assert window.equalizing
    release.set()
    qtbot.waitUntil(lambda: not window.equalizing, timeout=5000)
    assert not window.library_controller.scans
    connection = db.connect()
    assert [row["equalized"] for row in db.list_videos(connection, pid)] == [1, 0]
    connection.close()


def test_main_window_settings_apply_theme(qtbot, monkeypatch, tmp_path):
    from mp3_playlist_downloader.ui import settings_controller
    seed(monkeypatch, tmp_path)
    window = MainWindow(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(window)
    window.show()
    class FakeDialog:
        def __init__(self, settings, parent, test_url=None):
            self.result_settings = replace(settings, theme="dark", auto_equalize=True)
        def exec(self):
            return QDialog.DialogCode.Accepted
    monkeypatch.setattr(settings_controller, "SettingsDialog", FakeDialog)
    window.settings_button.click()
    assert window.settings.theme == "dark" and window.settings.auto_equalize and window.track_model.dark
    window.close()
