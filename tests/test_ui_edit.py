import shutil
import threading

from PySide6.QtWidgets import QFileDialog, QMessageBox
from mutagen.id3 import ID3

from mp3_playlist_downloader import db, services, tagging
from mp3_playlist_downloader.linking import LinkCancelled
from mp3_playlist_downloader.models import PlaylistMetadata, VideoMetadata
from mp3_playlist_downloader.settings import Settings
from mp3_playlist_downloader.ui.main_window import MainWindow


def setup_window(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    connection = db.connect()
    db.initialize(connection)
    pid, _ = db.add_playlist(connection, "url", PlaylistMetadata("Album", (VideoMetadata("aaaaaaaaaaa", "Song"),)), tmp_path / "music")
    video_id = db.list_videos(connection, pid)[0]["id"]
    connection.close()
    window = MainWindow(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.queue_controller.recovery is None and not window.library_controller.scans, timeout=5000)
    return window, pid, video_id


def test_point_to_file_copies_and_tags_in_worker(qtbot, monkeypatch, tmp_path, silent_mp3):
    window, pid, vid = setup_window(qtbot, monkeypatch, tmp_path)
    source = tmp_path / "external.mp3"
    shutil.copyfile(silent_mp3, source)
    original = source.read_bytes()
    monkeypatch.setattr(tagging, "load_cover", lambda *args: None)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(source), ""))
    window.edit_controller.point_to_file(vid)
    qtbot.waitUntil(lambda: not window.editing and not window.library_controller.scans, timeout=5000)
    connection = db.connect()
    row = db.list_videos(connection, pid)[0]
    connection.close()
    assert row["downloaded"] == 1 and row["file_path"] != str(source)
    assert source.read_bytes() == original
    assert str(ID3(row["file_path"])["TALB"]) == "Album"
    window.close()


def test_album_update_link_retags_and_clears_banner(qtbot, monkeypatch, tmp_path, silent_mp3):
    window, pid, vid = setup_window(qtbot, monkeypatch, tmp_path)
    path = tmp_path / "music" / "Album" / "song.mp3"
    shutil.copyfile(silent_mp3, path)
    tagging.tag_file(path, "Song", "Artist", "Old")
    connection = db.connect()
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,file_path=? WHERE id=?", (str(path), vid))
        connection.execute("UPDATE playlists SET title='Renamed',album_sync_pending=1 WHERE id=?", (pid,))
    connection.close()
    window.select_playlist(pid, scan=False)
    assert window.album_banner.isVisible()
    window.album_banner.linkActivated.emit("update")
    qtbot.waitUntil(lambda: not window.editing and not window.library_controller.scans, timeout=5000)
    assert str(ID3(path)["TALB"]) == "Renamed" and not window.album_banner.isVisible()
    assert window.queue_controller.progress_bar.value() == 100
    window.close()


def test_two_album_updates_finish_at_100_percent(qtbot, monkeypatch, tmp_path, silent_mp3):
    window, pid, vid = setup_window(qtbot, monkeypatch, tmp_path)
    folder = tmp_path / "music" / "Album"
    connection = db.connect()
    now = db.utc_now()
    with connection:
        connection.execute("INSERT INTO videos(playlist_id,video_id,title,position,created_at,updated_at) VALUES (?,?,?,?,?,?)", (pid, "bbbbbbbbbbb", "Second", 1, now, now))
        rows = db.list_videos(connection, pid)
        for index, row in enumerate(rows):
            path = folder / f"{index}.mp3"
            shutil.copyfile(silent_mp3, path)
            tagging.tag_file(path, row["title"], "Artist", "Old")
            connection.execute("UPDATE videos SET downloaded=1,file_path=? WHERE id=?", (str(path), row["id"]))
        connection.execute("UPDATE playlists SET album_sync_pending=1 WHERE id=?", (pid,))
    connection.close()
    window.select_playlist(pid, scan=False)
    window.edit_controller.sync_album()
    qtbot.waitUntil(lambda: not window.editing and not window.library_controller.scans, timeout=5000)
    assert window.queue_controller.progress_bar.value() == 100
    assert "2 updated, 0 failed" in window.statusBar().currentMessage()
    window.close()


def test_partial_album_failure_keeps_pending_and_reports(qtbot, monkeypatch, tmp_path, silent_mp3):
    window, pid, vid = setup_window(qtbot, monkeypatch, tmp_path)
    path = tmp_path / "music" / "Album" / "song.mp3"
    shutil.copyfile(silent_mp3, path)
    connection = db.connect()
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,file_path=? WHERE id=?", (str(path), vid))
        connection.execute("UPDATE playlists SET album_sync_pending=1 WHERE id=?", (pid,))
    connection.close()
    def fail(*args):
        raise OSError("sensitive path")
    monkeypatch.setattr(tagging, "retag_album", fail)
    window.select_playlist(pid, scan=False)
    window.edit_controller.sync_album()
    qtbot.waitUntil(lambda: not window.editing and not window.library_controller.scans, timeout=5000)
    assert "1 failed" in window.warning_banner.text() and "sensitive" not in window.warning_banner.text()
    assert window.album_banner.isVisible()
    window.close()


def test_cancelled_album_update_shows_partial_progress(qtbot, monkeypatch, tmp_path):
    window, pid, vid = setup_window(qtbot, monkeypatch, tmp_path)
    window.edit_controller.operation = "album"
    window.editing = True
    window.edit_controller._finished(services.AlbumSyncSummary(succeeded=1, cancelled=True, total=2), "")
    assert window.queue_controller.progress_bar.value() == 50
    assert "Cancelled" in window.statusBar().currentMessage()
    qtbot.waitUntil(lambda: not window.library_controller.scans, timeout=5000)
    window.close()


def test_close_during_link_waits_for_worker(qtbot, monkeypatch, tmp_path):
    window, pid, vid = setup_window(qtbot, monkeypatch, tmp_path)
    entered, release = threading.Event(), threading.Event()
    def slow(*args, **kwargs):
        entered.set()
        release.wait(5)
        raise LinkCancelled("cancelled")
    monkeypatch.setattr(services, "link_file", slow)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(tmp_path / "song.mp3"), ""))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.edit_controller.point_to_file(vid)
    qtbot.waitUntil(entered.is_set, timeout=5000)
    window.close()
    assert window.editing
    release.set()
    qtbot.waitUntil(lambda: not window.editing, timeout=5000)
    assert not window.library_controller.scans
