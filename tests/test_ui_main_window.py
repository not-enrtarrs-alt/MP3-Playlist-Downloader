from PySide6.QtCore import Qt

from mp3_playlist_downloader.settings import Settings
from mp3_playlist_downloader.ui.main_window import MainWindow


def test_window_builds_and_shows_warning(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    window = MainWindow(Settings(output_root=str(tmp_path / "music")), ["Settings invalid"])
    qtbot.addWidget(window)
    window.show()
    assert window.windowTitle() == "MP3 Playlist Downloader"
    assert window.warning_banner.isVisible()
    assert window.empty_message.text() == "No playlists yet"
    qtbot.mouseClick(window.log_button, Qt.MouseButton.LeftButton)
    window.append_log("test")
    assert window.log_drawer.isVisible() and "test" in window.log_drawer.toPlainText()
    window.close()
    assert (tmp_path / "data" / "settings.json").exists()


def test_app_refuses_second_instance(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QLockFile
    from mp3_playlist_downloader import app

    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path))
    held = QLockFile(str(tmp_path / "app.lock"))
    assert held.tryLock(0)
    messages = []
    monkeypatch.setattr(app.QMessageBox, "warning", lambda *args: messages.append(args[2]))
    try:
        assert app.run() == 2
        assert "instance" in messages[0].lower()
    finally:
        held.unlock()


def test_cached_sidebar_selection_never_calls_youtube(qtbot, monkeypatch, tmp_path):
    from mp3_playlist_downloader import db
    from mp3_playlist_downloader.models import PlaylistMetadata, VideoMetadata
    from mp3_playlist_downloader.youtube import client

    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    connection = db.connect()
    db.initialize(connection)
    for i in (1, 2):
        db.add_playlist(connection, f"https://www.youtube.com/playlist?list=PL{i}", PlaylistMetadata(f"Playlist {i}", (VideoMetadata(f"video{i}", f"Song {i}"),)), tmp_path / "music")
    connection.close()
    def forbidden(*args, **kwargs):
        raise AssertionError("Playlist selection must not call YouTube")
    monkeypatch.setattr(client.yt_dlp, "YoutubeDL", forbidden)
    window = MainWindow(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(window)
    window.show()
    window.track_model.set_all(True)
    window.sidebar.list.setCurrentRow(1)
    assert window.playlist_title.text() == "Playlist 2"
    assert window.track_model.index(0, 2).data() == "Song 2"
    assert not window.track_model.checked
    assert window.select_all_button.isEnabled()
    window.close()


def test_refresh_uses_worker_and_upserts_cached_rows(qtbot, monkeypatch, tmp_path):
    import json
    from pathlib import Path
    from mp3_playlist_downloader import db
    from mp3_playlist_downloader.models import PlaylistMetadata, VideoMetadata
    from mp3_playlist_downloader.youtube import client

    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    connection = db.connect()
    db.initialize(connection)
    pid, _ = db.add_playlist(connection, "https://www.youtube.com/playlist?list=PL123", PlaylistMetadata("Original", (VideoMetadata("aaaaaaaaaaa", "Old"), VideoMetadata("bbbbbbbbbbb", "Existing", position=1))), tmp_path / "music")
    connection.close()
    class Fake:
        def __init__(self, options):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            return json.loads((Path(__file__).parent / "fixtures" / "playlist_refreshed.json").read_text())
    monkeypatch.setattr(client.yt_dlp, "YoutubeDL", Fake)
    window = MainWindow(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(window)
    window.show()
    window.refresh_playlist(pid)
    assert not window.refresh_button.isEnabled()
    qtbot.waitUntil(lambda: window._refresh_worker is None, timeout=5000)
    assert window.playlist_title.text() == "Renamed Playlist"
    assert window.album_banner.isVisible()
    assert len(window.track_model.rows) == 3
    assert window.track_model.rows[-1]["video_id"] == "aaaaaaaaaaa"
    assert window.track_model.rows[-1]["in_playlist"] == 0
    window.close()


def test_selection_scans_extras_without_auto_deleting(qtbot, monkeypatch, tmp_path):
    from mp3_playlist_downloader import db
    from mp3_playlist_downloader.models import PlaylistMetadata, VideoMetadata
    from mp3_playlist_downloader.ui import library_controller

    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    connection = db.connect()
    db.initialize(connection)
    pid, _ = db.add_playlist(connection, "https://www.youtube.com/playlist?list=PL123", PlaylistMetadata("Original", (VideoMetadata("aaaaaaaaaaa", "Song"),)), tmp_path / "music")
    connection.close()
    extra = tmp_path / "music" / "Original" / "unknown.MP3"
    extra.write_bytes(b"keep me")
    reviews = []
    monkeypatch.setattr(library_controller.ExtraFilesDialog, "exec", lambda dialog: reviews.append(dialog.playlist_id))
    window = MainWindow(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: not window.library_controller.scans, timeout=5000)
    assert reviews == [pid]
    assert window.track_model.rows[-1]["_extra"]
    assert "additional" in window.extras_message.text()
    assert extra.read_bytes() == b"keep me"
    window.close()


def test_recovery_starts_only_after_schema_is_ready(qtbot, monkeypatch, tmp_path):
    from mp3_playlist_downloader import db
    from mp3_playlist_downloader.ui.queue_controller import QueueController

    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    original = QueueController._recover
    observed = []
    def checked_recover(controller):
        connection = db.connect()
        try:
            observed.append(connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
        finally:
            connection.close()
        original(controller)
    monkeypatch.setattr(QueueController, "_recover", checked_recover)
    window = MainWindow(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(window)
    assert observed == [str(db.SCHEMA_VERSION)]
    qtbot.waitUntil(lambda: window.queue_controller.recovery is None, timeout=5000)
    window.close()


def test_removing_playlist_preserves_files(qtbot, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    from mp3_playlist_downloader import db
    from mp3_playlist_downloader.models import PlaylistMetadata, VideoMetadata

    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    connection = db.connect()
    db.initialize(connection)
    pid, _ = db.add_playlist(connection, "url", PlaylistMetadata("Playlist", (VideoMetadata("aaaaaaaaaaa", "Song"),)), tmp_path / "music")
    path = tmp_path / "music" / "Playlist" / "Song.mp3"
    path.write_bytes(b"audio")
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,file_path=? WHERE playlist_id=?", (str(path), pid))
    connection.close()
    window = MainWindow(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.queue_controller.recovery is None and not window.library_controller.scans, timeout=5000)
    window.playlist_actions.remove_playlist(pid)
    assert path.read_bytes() == b"audio"
    connection = db.connect()
    assert not db.list_playlists(connection)
    connection.close()
    window.close()
