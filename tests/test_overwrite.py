import shutil

import pytest

from mp3_playlist_downloader import paths
from mp3_playlist_downloader.settings import Settings
from mp3_playlist_downloader.youtube.download import download_video
from mp3_playlist_downloader.youtube.errors import YouTubeError


def fake_downloader(silent_mp3, during=None):
    class Fake:
        def __init__(self, options):
            self.options = options
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            shutil.copyfile(silent_mp3, self.options["outtmpl"].replace("%(ext)s", "mp3"))
            if during:
                during()
    return Fake


def tracked(folder):
    old = folder / "Existing.mp3"
    old.write_bytes(b"original audio")
    video = {"video_id": "aaaaaaaaaaa", "title": "Song", "uploader": "Artist", "downloaded": 1, "file_path": str(old)}
    return old, video


def test_overwrite_recycles_only_after_new_file_ready(monkeypatch, tmp_path, silent_mp3):
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    old, video = tracked(tmp_path)
    recycled = tmp_path / "recycled.bin"
    def recycle(path):
        assert old.read_bytes() == b"original audio"
        assert list(tmp_path.glob(".tmp-*.mp3"))
        shutil.move(path, recycled)
    result = download_video(video, "Album", tmp_path, Settings(), overwrite=True, recycle=recycle,
                            downloader_factory=fake_downloader(silent_mp3), cover_loader=lambda *args: None)
    assert result.file_path == old and old.is_file() and recycled.read_bytes() == b"original audio"
    assert not list(tmp_path.glob(".tmp-*"))


def test_recycle_failure_preserves_old_and_cleans_temp(monkeypatch, tmp_path, silent_mp3):
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    old, video = tracked(tmp_path)
    def fail(path):
        raise OSError("recycle failure")
    with pytest.raises(OSError):
        download_video(video, "Album", tmp_path, Settings(), overwrite=True, recycle=fail,
                       downloader_factory=fake_downloader(silent_mp3), cover_loader=lambda *args: None)
    assert old.read_bytes() == b"original audio" and not list(tmp_path.glob(".tmp-*"))


def test_overwrite_refuses_file_changed_during_download(monkeypatch, tmp_path, silent_mp3):
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    old, video = tracked(tmp_path)
    calls = []
    with pytest.raises(YouTubeError, match="changed"):
        download_video(video, "Album", tmp_path, Settings(), overwrite=True, recycle=calls.append,
                       downloader_factory=fake_downloader(silent_mp3, lambda: old.write_bytes(b"user update with different length")), cover_loader=lambda *args: None)
    assert not calls and old.read_bytes() == b"user update with different length"


def test_overwrite_race_does_not_replace_new_unrelated_file(monkeypatch, tmp_path, silent_mp3):
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    old, video = tracked(tmp_path)
    recycled = tmp_path / "recycled.bin"
    def recycle(path):
        shutil.move(path, recycled)
        old.write_bytes(b"new unrelated file")
    result = download_video(video, "Album", tmp_path, Settings(), overwrite=True, recycle=recycle,
                            downloader_factory=fake_downloader(silent_mp3), cover_loader=lambda *args: None)
    assert old.read_bytes() == b"new unrelated file" and result.file_path != old
    assert recycled.read_bytes() == b"original audio"


def test_persisted_overwrite_queue_recycles_and_resets_equalization(monkeypatch, tmp_path, silent_mp3):
    from mp3_playlist_downloader import db, queue
    from mp3_playlist_downloader.models import PlaylistMetadata, VideoMetadata
    from mp3_playlist_downloader.youtube import download as downloader

    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", fake_downloader(silent_mp3))
    monkeypatch.setattr(downloader.tagging, "load_cover", lambda *args: None)
    connection = db.connect(tmp_path / "app.db")
    db.initialize(connection)
    pid, _ = db.add_playlist(connection, "url", PlaylistMetadata("Album", (VideoMetadata("aaaaaaaaaaa", "Song"),)), tmp_path / "music")
    old = tmp_path / "music" / "Album" / "old.mp3"
    old.write_bytes(b"original audio")
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,equalized=1,file_path=?,file_size=? WHERE playlist_id=?", (str(old), old.stat().st_size, pid))
    settings = Settings(overwrite_existing=True)
    assert queue.enqueue_missing(connection, pid, settings, include_existing=True) == 1
    connection.close()
    connection = db.connect(tmp_path / "app.db")
    recycled = tmp_path / "recycled.bin"
    monkeypatch.setattr(downloader, "send2trash", lambda path: shutil.move(path, recycled))
    summary = queue.run_queue(connection, settings)
    row = db.list_videos(connection, pid)[0]
    connection.close()
    assert summary.downloaded == 1 and row["downloaded"] == 1 and row["equalized"] == 0
    assert row["file_path"] == str(old) and recycled.read_bytes() == b"original audio"
