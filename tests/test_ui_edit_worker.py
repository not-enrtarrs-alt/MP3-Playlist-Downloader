import shutil

from PySide6.QtCore import QThreadPool

from mp3_playlist_downloader import db, tagging
from mp3_playlist_downloader.models import PlaylistMetadata, VideoMetadata
from mp3_playlist_downloader.settings import Settings
from mp3_playlist_downloader.ui.edit_controller import EditWorker


def test_link_worker_owns_connection_and_preserves_source(qtbot, monkeypatch, tmp_path, silent_mp3):
    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(tagging, "load_cover", lambda *args: None)
    connection = db.connect()
    db.initialize(connection)
    pid, _ = db.add_playlist(connection, "url", PlaylistMetadata("Album", (VideoMetadata("aaaaaaaaaaa", "Song"),)), tmp_path / "music")
    video_id = db.list_videos(connection, pid)[0]["id"]
    connection.close()
    source = tmp_path / "source.mp3"
    shutil.copyfile(silent_mp3, source)
    before = source.read_bytes()
    worker = EditWorker("link", video_id, Settings(), str(source))
    with qtbot.waitSignal(worker.signals.completed, timeout=5000) as signal:
        QThreadPool.globalInstance().start(worker)
    assert signal.args[0].file_path.is_file() and not signal.args[1]
    assert source.read_bytes() == before
    connection = db.connect()
    assert db.list_videos(connection, pid)[0]["downloaded"] == 1
    connection.close()
