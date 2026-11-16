from PySide6.QtCore import QThreadPool

from mp3_playlist_downloader import db
from mp3_playlist_downloader.models import PlaylistMetadata
from mp3_playlist_downloader.ui.library_workers import ActionWorker, ScanWorker


def test_scan_and_keep_run_in_workers(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    connection = db.connect()
    db.initialize(connection)
    pid, _ = db.add_playlist(connection, "url", PlaylistMetadata("Playlist", ()), tmp_path / "music")
    folder = tmp_path / "music" / "Playlist"
    (folder / "extra.mp3").write_bytes(b"data")
    connection.close()
    worker = ScanWorker(pid)
    with qtbot.waitSignal(worker.signals.completed, timeout=5000) as result:
        QThreadPool.globalInstance().start(worker)
    assert not result.args[2] and len(result.args[1].new_extra_ids) == 1
    action = ActionWorker([("keep_extra", result.args[1].new_extra_ids[0])])
    with qtbot.waitSignal(action.signals.completed, timeout=5000) as status:
        QThreadPool.globalInstance().start(action)
    assert status.args == [1, 0] and (folder / "extra.mp3").exists()
    connection = db.connect()
    assert connection.execute("SELECT disposition FROM extra_files").fetchone()[0] == "kept"
    connection.close()
