from PySide6.QtCore import QThreadPool

from mp3_playlist_downloader import db, equalizer
from mp3_playlist_downloader.models import PlaylistMetadata, VideoMetadata
from mp3_playlist_downloader.settings import Settings
from mp3_playlist_downloader.ui.equalizer_controller import EqualizeWorker


def test_equalize_worker_uses_own_connection_and_marks_success(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(equalizer, "discover", lambda settings: "mp3gain.exe")
    calls = []
    monkeypatch.setattr(equalizer, "apply", lambda path, settings: calls.append(path))
    connection = db.connect()
    db.initialize(connection)
    pid, _ = db.add_playlist(connection, "url", PlaylistMetadata("Playlist", (VideoMetadata("aaaaaaaaaaa", "Song"),)), tmp_path / "music")
    path = tmp_path / "music" / "Playlist" / "song.mp3"
    path.write_bytes(b"audio")
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,file_path=? WHERE playlist_id=?", (str(path), pid))
    video_id = db.list_videos(connection, pid)[0]["id"]
    connection.close()
    worker = EqualizeWorker([video_id], Settings())
    with qtbot.waitSignal(worker.signals.completed, timeout=5000) as signal:
        QThreadPool.globalInstance().start(worker)
    assert signal.args[0].succeeded == 1 and not signal.args[1]
    connection = db.connect()
    assert db.list_videos(connection, pid)[0]["equalized"] == 1
    connection.close()
    assert calls == [path]
