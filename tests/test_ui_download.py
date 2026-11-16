import threading

from PySide6.QtWidgets import QMessageBox

from mp3_playlist_downloader import db, paths, queue
from mp3_playlist_downloader.models import PlaylistMetadata, VideoMetadata
from mp3_playlist_downloader.settings import Settings
from mp3_playlist_downloader.ui.main_window import MainWindow
from mp3_playlist_downloader.youtube.download import DownloadCancelled, DownloadResult


def create_playlist(monkeypatch, tmp_path):
    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    connection = db.connect()
    db.initialize(connection)
    pid, _ = db.add_playlist(connection, "https://www.youtube.com/playlist?list=PL123", PlaylistMetadata("Playlist", (VideoMetadata("aaaaaaaaaaa", "Song"),)), tmp_path / "music")
    connection.close()
    return pid


def test_download_button_runs_worker_and_updates_db(qtbot, monkeypatch, tmp_path):
    pid = create_playlist(monkeypatch, tmp_path)
    original = queue.run_queue
    entered, release = threading.Event(), threading.Event()
    def fake_download(video, title, folder, settings, **kwargs):
        entered.set()
        release.wait(5)
        path = folder / "Song.mp3"
        path.write_bytes(b"audio")
        return DownloadResult(path, 5)
    monkeypatch.setattr(queue, "run_queue", lambda connection, settings, **kwargs: original(connection, settings, download=fake_download, **kwargs))
    window = MainWindow(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.queue_controller.recovery is None and not window.library_controller.scans, timeout=5000)
    assert window.download_button.isEnabled()
    window.download_button.click()
    qtbot.waitUntil(entered.is_set, timeout=5000)
    assert window.queue_running and not window.sidebar.add_button.isEnabled() and window.queue_controller.cancel_button.isEnabled()
    release.set()
    qtbot.waitUntil(lambda: not window.queue_running and not window.library_controller.scans, timeout=5000)
    connection = db.connect()
    row = db.list_videos(connection, pid)[0]
    connection.close()
    assert row["downloaded"] == 1 and row["file_size"] == 5
    assert "1 downloaded" in window.queue_controller.progress_label.text()
    window.close()


def test_close_cancels_and_keeps_pending_queue(qtbot, monkeypatch, tmp_path):
    pid = create_playlist(monkeypatch, tmp_path)
    original = queue.run_queue
    entered = threading.Event()
    def fake_download(video, title, folder, settings, **kwargs):
        entered.set()
        while not kwargs["cancelled"]():
            entered.wait(0.01)
        raise DownloadCancelled()
    monkeypatch.setattr(queue, "run_queue", lambda connection, settings, **kwargs: original(connection, settings, download=fake_download, **kwargs))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window = MainWindow(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.queue_controller.recovery is None and not window.library_controller.scans, timeout=5000)
    window.download_button.click()
    qtbot.waitUntil(entered.is_set, timeout=5000)
    window.close()
    qtbot.waitUntil(lambda: not window.queue_running, timeout=5000)
    assert not window.library_controller.scans
    connection = db.connect()
    assert db.list_videos(connection, pid)[0]["download_state"] == "queued"
    connection.close()


def test_startup_recovers_pending_without_autostart(qtbot, monkeypatch, tmp_path):
    pid = create_playlist(monkeypatch, tmp_path)
    connection = db.connect()
    with connection:
        connection.execute("UPDATE videos SET download_state='downloading' WHERE playlist_id=?", (pid,))
    connection.close()
    window = MainWindow(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.queue_controller.recovery is None, timeout=5000)
    assert window.queue_controller.banner.isVisible()
    assert "1 downloads pending" in window.queue_controller.banner.text()
    assert not window.queue_running
    connection = db.connect()
    assert db.list_videos(connection, pid)[0]["download_state"] == "queued"
    connection.close()
    window.close()


def test_delete_selected_recycles_before_reset(qtbot, monkeypatch, tmp_path):
    from pathlib import Path
    from mp3_playlist_downloader import library

    pid = create_playlist(monkeypatch, tmp_path)
    path = tmp_path / "music" / "Playlist" / "Song.mp3"
    path.write_bytes(b"audio")
    connection = db.connect()
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,equalized=1,file_path=?,file_size=5 WHERE playlist_id=?", (str(path), pid))
    connection.close()
    calls = []
    def recycler(file_path):
        calls.append(file_path)
        Path(file_path).unlink()
    monkeypatch.setattr(library, "send2trash", recycler)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window = MainWindow(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.queue_controller.recovery is None and not window.library_controller.scans, timeout=5000)
    window.track_model.set_all(True)
    assert window.delete_button.isEnabled()
    window.delete_button.click()
    qtbot.waitUntil(lambda: window.library_controller.action is None and not window.library_controller.scans, timeout=5000)
    connection = db.connect()
    row = db.list_videos(connection, pid)[0]
    connection.close()
    assert calls == [str(path)] and not row["downloaded"] and not row["equalized"]
    window.close()


def test_overwrite_confirmation_queues_existing_only_after_yes(qtbot, monkeypatch, tmp_path):
    pid = create_playlist(monkeypatch, tmp_path)
    path = tmp_path / "music" / "Playlist" / "Song.mp3"
    path.write_bytes(b"original")
    connection = db.connect()
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,file_path=? WHERE playlist_id=?", (str(path), pid))
    connection.close()
    window = MainWindow(Settings(output_root=str(tmp_path / "music"), overwrite_existing=True))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.queue_controller.recovery is None and not window.library_controller.scans, timeout=5000)
    assert window.download_button.isEnabled()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    window.download_button.click()
    connection = db.connect()
    assert db.list_videos(connection, pid)[0]["download_state"] == "idle"
    connection.close()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    starts = []
    monkeypatch.setattr(window.queue_controller, "_start", lambda: starts.append(True))
    window.download_button.click()
    connection = db.connect()
    assert db.list_videos(connection, pid)[0]["download_state"] == "queued"
    connection.close()
    assert starts == [True] and path.read_bytes() == b"original"
    window.close()


def test_redownload_confirmation_resets_attempts(qtbot, monkeypatch, tmp_path):
    pid = create_playlist(monkeypatch, tmp_path)
    connection = db.connect()
    video_id = db.list_videos(connection, pid)[0]["id"]
    with connection:
        connection.execute("UPDATE videos SET attempts=3,download_state='failed' WHERE id=?", (video_id,))
    connection.close()
    window = MainWindow(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.queue_controller.recovery is None and not window.library_controller.scans, timeout=5000)
    starts = []
    monkeypatch.setattr(window.queue_controller, "_start", lambda: starts.append(True))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.queue_controller.redownload(video_id)
    connection = db.connect()
    row = db.list_videos(connection, pid)[0]
    connection.close()
    assert row["download_state"] == "queued" and row["attempts"] == 0 and starts == [True]
    window.close()


def test_progress_displays_overall_file_speed_and_eta(qtbot, monkeypatch, tmp_path):
    create_playlist(monkeypatch, tmp_path)
    window = MainWindow(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.queue_controller.recovery is None and not window.library_controller.scans, timeout=5000)
    controller = window.queue_controller
    controller.total, controller.finished_count = 4, 1
    controller._started(1, "Song")
    controller._progress(50.0, 1.5 * 1048576, 14)
    assert controller.progress_bar.value() == 37
    assert "File 50%" in controller.progress_bar.format()
    assert "2/4" in controller.progress_label.text() and "1.5 MB/s" in controller.progress_label.text() and "ETA 00:14" in controller.progress_label.text()
    window.close()
