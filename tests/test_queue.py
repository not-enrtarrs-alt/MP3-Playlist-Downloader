import pytest

from mp3_playlist_downloader import db, paths, queue
from mp3_playlist_downloader.models import PlaylistMetadata, VideoMetadata
from mp3_playlist_downloader.settings import Settings
from mp3_playlist_downloader.youtube.download import DownloadCancelled, DownloadResult
from mp3_playlist_downloader.youtube.errors import NetworkError, RateLimitedError, UnavailableError, YouTubeError


@pytest.fixture
def playlist(tmp_path):
    connection = db.connect(tmp_path / "app.db")
    db.initialize(connection)
    metadata = PlaylistMetadata("Queue", tuple(VideoMetadata(f"video{i:06}", f"Song {i}", position=i) for i in range(3)))
    pid, _ = db.add_playlist(connection, "url", metadata, tmp_path / "music")
    yield connection, pid, Settings(output_root=str(tmp_path / "music"))
    connection.close()


def test_queue_sequential_and_success(playlist, monkeypatch):
    connection, pid, settings = playlist
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    assert queue.enqueue_missing(connection, pid, settings) == 3
    calls = []
    def download(video, title, folder, settings, **kwargs):
        calls.append(video["position"])
        path = folder / f"{video['position']}.mp3"
        path.write_bytes(b"audio")
        return DownloadResult(path, 5)
    result = queue.run_queue(connection, settings, download=download)
    assert calls == [0, 1, 2] and result.downloaded == 3
    assert queue.pending_count(connection) == 0
    assert all(row["downloaded"] and row["download_state"] == "idle" for row in db.list_videos(connection, pid))


def test_ffmpeg_missing_does_not_queue(playlist, monkeypatch):
    connection, pid, settings = playlist
    monkeypatch.setattr(paths, "find_tool", lambda *args: None)
    with pytest.raises(YouTubeError):
        queue.enqueue_missing(connection, pid, settings)
    assert queue.pending_count(connection) == 0


def test_overwrite_queue_requires_explicit_include_existing(playlist, monkeypatch):
    connection, pid, settings = playlist
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    old = db.list_playlists(connection)[0]["folder_path"]
    from pathlib import Path
    old = Path(old) / "old.mp3"
    old.write_bytes(b"old")
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,file_path=? WHERE playlist_id=? AND position=0", (str(old), pid))
    assert queue.existing_count(connection, pid) == 1
    assert queue.enqueue_missing(connection, pid, settings) == 2
    assert db.list_videos(connection, pid)[0]["download_state"] == "idle"
    assert queue.enqueue_missing(connection, pid, settings, include_existing=True) == 1
    calls = []
    def download(video, title, folder, settings, **kwargs):
        calls.append((video["position"], kwargs["overwrite"]))
        path = folder / f"new-{video['position']}.mp3"
        path.write_bytes(b"new")
        return DownloadResult(path, 3)
    result = queue.run_queue(connection, settings, download=download)
    assert result.downloaded == 3 and calls == [(0, True), (1, False), (2, False)]


def test_overwrite_does_not_touch_shared_tracked_path(playlist, monkeypatch):
    connection, pid, settings = playlist
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    from pathlib import Path
    path = Path(db.list_playlists(connection)[0]["folder_path"]) / "shared.mp3"
    path.write_bytes(b"keep")
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,file_path=? WHERE playlist_id=? AND position IN (0,1)", (str(path), pid))
        connection.execute("UPDATE videos SET download_state='queued' WHERE playlist_id=? AND position=0", (pid,))
    calls = []
    queue.run_queue(connection, settings, download=lambda *args, **kwargs: calls.append(True))
    rows = db.list_videos(connection, pid)
    assert not calls and path.read_bytes() == b"keep"
    assert rows[0]["downloaded"] == 1 and rows[0]["download_state"] == "failed"


def test_rate_limit_preserves_queue_and_attempts(playlist, monkeypatch):
    connection, pid, settings = playlist
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    queue.enqueue_missing(connection, pid, settings)
    def limited(*args, **kwargs):
        raise RateLimitedError("limited")
    result = queue.run_queue(connection, settings, download=limited)
    assert result.rate_limited_until and queue.pending_count(connection) == 3
    assert db.list_videos(connection, pid)[0]["attempts"] == 0
    assert connection.execute("SELECT value FROM meta WHERE key='queue_pause_reason'").fetchone()[0] == "rate_limited"


def test_rate_limit_policy_allows_three_auto_retries_then_manual_reset(playlist, monkeypatch):
    from datetime import datetime, timezone
    connection, pid, settings = playlist
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    queue.enqueue_missing(connection, pid, settings)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    def limited(*args, **kwargs):
        raise RateLimitedError("limited")
    for streak in range(1, 5):
        result = queue.run_queue(connection, settings, download=limited, clock=lambda: now)
        state = queue.pause_state(connection)
        assert state.streak == streak and state.until == result.rate_limited_until
        assert state.auto_retry_allowed is (streak <= 3)
        assert queue.pending_count(connection) == 3
        if streak < 4:
            queue.clear_pause(connection, manual=False)
            assert queue.pause_state(connection).streak == streak
    queue.clear_pause(connection, manual=True)
    assert queue.pause_state(connection) == queue.PauseState("", "", 0)


def test_success_resets_rate_limit_pause(playlist, monkeypatch):
    connection, pid, settings = playlist
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    queue.enqueue_missing(connection, pid, settings)
    def limited(*args, **kwargs):
        raise RateLimitedError("limited")
    queue.run_queue(connection, settings, download=limited)
    def succeed(video, title, folder, settings, **kwargs):
        path = folder / f"{video['video_id']}.mp3"
        path.write_bytes(b"audio")
        return DownloadResult(path, 5)
    queue.run_queue(connection, settings, download=succeed)
    assert queue.pause_state(connection) == queue.PauseState("", "", 0)


def test_network_retry_failure_and_unavailable_continue(playlist, monkeypatch):
    connection, pid, settings = playlist
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    queue.enqueue_missing(connection, pid, settings)
    calls, delays = [], []
    def download(video, title, folder, settings, **kwargs):
        calls.append(video["position"])
        if video["position"] == 0:
            raise NetworkError("private detail")
        if video["position"] == 1:
            raise UnavailableError("private detail")
        path = folder / "good.mp3"
        path.write_bytes(b"audio")
        return DownloadResult(path, 5)
    result = queue.run_queue(connection, settings, download=download, wait=delays.append)
    assert calls == [0, 0, 1, 2] and delays == [5]
    assert (result.downloaded, result.failed, result.unavailable) == (1, 1, 1)
    rows = db.list_videos(connection, pid)
    assert rows[0]["attempts"] == 1 and rows[0]["error_kind"] == "network"
    assert rows[1]["unavailable"] == 1 and "private detail" not in rows[1]["last_error"]


def test_conversion_failure_stores_safe_actionable_error(playlist, monkeypatch):
    from mp3_playlist_downloader.youtube.errors import AudioConversionError
    connection, pid, settings = playlist
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    queue.enqueue_missing(connection, pid, settings)
    def fail(*args, **kwargs):
        raise AudioConversionError("secret-cookie-path token=private")
    summary = queue.run_queue(connection, settings, download=fail)
    assert summary.failed == 3
    error = db.list_videos(connection, pid)[0]["last_error"]
    assert "ffmpeg" in error and "secret" not in error and "private" not in error


def test_cancel_and_recovery(playlist, monkeypatch):
    connection, pid, settings = playlist
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    queue.enqueue_missing(connection, pid, settings)
    def cancel(*args, **kwargs):
        raise DownloadCancelled()
    result = queue.run_queue(connection, settings, download=cancel)
    assert result.cancelled and queue.pending_count(connection) == 3
    folder = db.list_playlists(connection)[0]["folder_path"]
    from pathlib import Path
    stale = Path(folder) / (".tmp-" + "a" * 32 + ".part")
    untouched = Path(folder) / ".tmp-personal.mp3"
    stale.write_bytes(b"partial")
    untouched.write_bytes(b"user")
    with connection:
        connection.execute("UPDATE videos SET download_state='downloading' WHERE position=0")
    assert queue.recover_interrupted(connection) == 1
    assert not stale.exists() and untouched.exists() and queue.pending_count(connection) == 3


def test_removed_and_unavailable_queued_rows_are_not_downloaded(playlist, monkeypatch):
    connection, pid, settings = playlist
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    queue.enqueue_missing(connection, pid, settings)
    with connection:
        connection.execute("UPDATE videos SET in_playlist=0 WHERE playlist_id=? AND position=0", (pid,))
        connection.execute("UPDATE videos SET unavailable=1 WHERE playlist_id=? AND position=1", (pid,))
    calls = []
    def download(video, title, folder, settings, **kwargs):
        calls.append(video["position"])
        path = folder / "good.mp3"
        path.write_bytes(b"audio")
        return DownloadResult(path, 5)
    result = queue.run_queue(connection, settings, download=download)
    assert calls == [2] and result.downloaded == 1
    assert all(row["download_state"] == "idle" for row in db.list_videos(connection, pid))


def test_real_pipeline_with_fake_ytdlp_writes_tagged_tracked_file(playlist, monkeypatch, silent_mp3):
    import shutil
    from mutagen.id3 import ID3
    from mp3_playlist_downloader.youtube import download as downloader

    connection, pid, settings = playlist
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    class Fake:
        def __init__(self, options):
            self.options = options
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            shutil.copyfile(silent_mp3, self.options["outtmpl"].replace("%(ext)s", "mp3"))
            with open(self.options["outtmpl"].replace("%(ext)s", "jpg"), "wb") as image:
                image.write(b"\xff\xd8\xfffakejpeg")
    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", Fake)
    with connection:
        connection.execute("UPDATE videos SET unavailable=1 WHERE playlist_id=? AND position>0", (pid,))
    assert queue.enqueue_missing(connection, pid, settings) == 1
    summary = queue.run_queue(connection, settings)
    row = db.list_videos(connection, pid)[0]
    assert summary.downloaded == 1 and row["downloaded"] == 1
    assert row["file_path"] and ID3(row["file_path"])["TALB"].text == ["Queue"]
    assert ID3(row["file_path"]).getall("APIC")


@pytest.mark.parametrize("succeeds", [True, False])
def test_auto_equalization_persists_only_success(playlist, monkeypatch, silent_mp3, succeeds):
    import shutil
    from mp3_playlist_downloader import equalizer
    from mp3_playlist_downloader.youtube import download as downloader

    connection, pid, settings = playlist
    settings.auto_equalize = True
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    def gain(path, config):
        if not succeeds:
            raise equalizer.EqualizerMissing(equalizer.MISSING_MESSAGE)
    monkeypatch.setattr(equalizer, "apply", gain)
    class Fake:
        def __init__(self, options):
            self.options = options
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            shutil.copyfile(silent_mp3, self.options["outtmpl"].replace("%(ext)s", "mp3"))
            with open(self.options["outtmpl"].replace("%(ext)s", "jpg"), "wb") as image:
                image.write(b"\xff\xd8\xfffakejpeg")
    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", Fake)
    with connection:
        connection.execute("UPDATE videos SET unavailable=1 WHERE playlist_id=? AND position>0", (pid,))
    queue.enqueue_missing(connection, pid, settings)
    assert queue.run_queue(connection, settings).downloaded == 1
    row = db.list_videos(connection, pid)[0]
    assert row["downloaded"] == 1 and bool(row["equalized"]) is succeeds
    assert row["error_kind"] == (None if succeeds else "equalize")
