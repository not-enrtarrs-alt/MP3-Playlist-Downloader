"""Right-click manual rename behavior without real network or Recycle Bin."""

import base64
import shutil
import zlib

from mutagen.id3 import ID3
from PySide6.QtWidgets import QInputDialog

from mp3_playlist_downloader import db, demo, renaming, tagging
from mp3_playlist_downloader.models import PlaylistMetadata, VideoMetadata
from mp3_playlist_downloader.settings import Settings
from mp3_playlist_downloader.ui.main_window import MainWindow


def setup_window(qtbot, monkeypatch, tmp_path, downloaded=False):
    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    connection = db.connect()
    db.initialize(connection)
    metadata = PlaylistMetadata("Album", (VideoMetadata("aaaaaaaaaaa", "Artist - Song (Official Audio)", uploader="Artist"),))
    pid, _ = db.add_playlist(connection, "url", metadata, tmp_path / "music")
    vid = db.list_videos(connection, pid)[0]["id"]
    path = tmp_path / "music" / "Album" / "Original.mp3"
    if downloaded:
        path.write_bytes(zlib.decompress(base64.b64decode(demo._SILENCE)))
        tagging.tag_file(path, "Song", "Artist", "Album", b"\xff\xd8\xffcover")
        with connection:
            connection.execute("UPDATE videos SET downloaded=1,file_path=?,file_size=? WHERE id=?", (str(path), path.stat().st_size, vid))
    connection.close()
    window = MainWindow(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.queue_controller.recovery is None and not window.library_controller.scans, timeout=5000)
    return window, pid, vid, path


def test_right_click_rename_updates_file_tag_and_ui(qtbot, monkeypatch, tmp_path):
    from mp3_playlist_downloader.ui import library_controller
    window, pid, vid, old = setup_window(qtbot, monkeypatch, tmp_path, downloaded=True)
    prompts = []
    def prompt(*args, **kwargs):
        prompts.append(kwargs.get("text"))
        return "My name", True
    monkeypatch.setattr(QInputDialog, "getText", prompt)
    monkeypatch.setattr(library_controller, "_execute_menu", lambda menu, point: next(action for action in menu.actions() if action.text() == "Rename track…"))
    recycled = tmp_path / "recycled.mp3"
    monkeypatch.setattr(renaming, "send2trash", lambda path: shutil.move(path, recycled))
    index = window.track_model.index(0, 2)
    window.library_controller.show_context_menu(window.track_table.visualRect(index).center())
    qtbot.waitUntil(lambda: not window.editing and not window.library_controller.scans, timeout=5000)
    connection = db.connect()
    row = db.list_videos(connection, pid)[0]
    connection.close()
    assert prompts == ["Song"] and row["custom_title"] == "My name"
    assert row["title"] == "Artist - Song (Official Audio)"
    assert window.track_model.index(0, 2).data() == "My name"
    assert str(ID3(row["file_path"])["TIT2"]) == "My name"
    assert recycled.exists() and not old.exists()
    window.close()


def test_rename_missing_track_and_cancel(qtbot, monkeypatch, tmp_path):
    window, pid, vid, path = setup_window(qtbot, monkeypatch, tmp_path)
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Ignored", False))
    window.edit_controller.rename_track(vid)
    assert not window.editing
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Custom title", True))
    window.edit_controller.rename_track(vid)
    qtbot.waitUntil(lambda: not window.editing and not window.library_controller.scans, timeout=5000)
    connection = db.connect()
    row = db.list_videos(connection, pid)[0]
    connection.close()
    assert row["custom_title"] == "Custom title" and not row["downloaded"] and not path.exists()
    assert window.track_model.index(0, 2).data() == "Custom title"
    window.close()


def test_rename_disabled_while_queue_running(qtbot, monkeypatch, tmp_path):
    window, pid, vid, _ = setup_window(qtbot, monkeypatch, tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("Rename dialog must not open while the queue is running")
    monkeypatch.setattr(QInputDialog, "getText", forbidden)
    window.queue_running = True
    window.edit_controller.rename_track(vid)
    window.queue_running = False
    window.close()


def test_native_rename_dialog_saves_title(qtbot, monkeypatch, tmp_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    window, pid, vid, _ = setup_window(qtbot, monkeypatch, tmp_path)
    def accept_dialog():
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, QInputDialog):
            dialog.setTextValue("Native dialog title")
            dialog.accept()
    QTimer.singleShot(0, accept_dialog)
    window.edit_controller.rename_track(vid)
    qtbot.waitUntil(lambda: not window.editing and not window.library_controller.scans, timeout=5000)
    connection = db.connect()
    assert db.list_videos(connection, pid)[0]["custom_title"] == "Native dialog title"
    connection.close()
    window.close()


def test_empty_rename_is_rejected_without_changing_track(qtbot, monkeypatch, tmp_path):
    window, pid, vid, _ = setup_window(qtbot, monkeypatch, tmp_path)
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("   ", True))
    window.edit_controller.rename_track(vid)
    qtbot.waitUntil(lambda: not window.editing and not window.library_controller.scans, timeout=5000)
    connection = db.connect()
    assert db.list_videos(connection, pid)[0]["custom_title"] is None
    connection.close()
    assert "non-empty" in window.warning_banner.text()
    window.close()
