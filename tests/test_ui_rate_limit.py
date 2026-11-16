from datetime import datetime, timedelta, timezone

from mp3_playlist_downloader import db, paths, queue
from mp3_playlist_downloader.models import PlaylistMetadata, VideoMetadata
from mp3_playlist_downloader.settings import Settings
from mp3_playlist_downloader.ui.main_window import MainWindow


def window_with_pending(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(paths, "find_tool", lambda *args: "ffmpeg")
    connection = db.connect()
    db.initialize(connection)
    pid, _ = db.add_playlist(connection, "url", PlaylistMetadata("Playlist", (VideoMetadata("aaaaaaaaaaa", "Song"),)), tmp_path / "music")
    with connection:
        connection.execute("UPDATE videos SET download_state='queued' WHERE playlist_id=?", (pid,))
    connection.close()
    window = MainWindow(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.queue_controller.recovery is None and not window.library_controller.scans, timeout=5000)
    return window


def test_startup_pending_never_auto_starts(qtbot, monkeypatch, tmp_path):
    window = window_with_pending(qtbot, monkeypatch, tmp_path)
    assert window.queue_controller.banner.isVisible()
    assert not window.queue_controller._countdown.isActive()
    assert not window.queue_running
    window.close()


def test_live_countdown_auto_resume_preserves_streak(qtbot, monkeypatch, tmp_path):
    window = window_with_pending(qtbot, monkeypatch, tmp_path)
    controller = window.queue_controller
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    controller._clock = lambda: now
    connection = db.connect()
    with connection:
        queue._set_meta(connection, "queue_rate_limit_streak", "2")
        queue._set_meta(connection, "queue_pause_reason", "rate_limited")
        queue._set_meta(connection, "queue_paused_until", (now + timedelta(seconds=65)).isoformat())
    state = queue.pause_state(connection)
    connection.close()
    starts = []
    monkeypatch.setattr(controller, "_start", lambda: starts.append(True))
    controller._arm_countdown(state)
    assert "00:01:05" in controller.banner.text()
    controller._clock = lambda: now + timedelta(seconds=65)
    controller._tick_countdown()
    assert starts == [True]
    connection = db.connect()
    assert queue.pause_state(connection).streak == 2
    connection.close()
    controller.hide_banner()
    window.close()


def test_retry_cap_and_dismiss_cancel_auto_resume(qtbot, monkeypatch, tmp_path):
    window = window_with_pending(qtbot, monkeypatch, tmp_path)
    controller = window.queue_controller
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    controller._clock = lambda: now
    starts = []
    monkeypatch.setattr(controller, "resume", lambda automatic=False: starts.append(automatic))
    controller._arm_countdown(queue.PauseState("rate_limited", now.isoformat(), 4))
    assert not starts and "resume manually" in controller.banner.text()
    controller._arm_countdown(queue.PauseState("rate_limited", (now + timedelta(seconds=5)).isoformat(), 1))
    controller.hide_banner()
    controller._clock = lambda: now + timedelta(seconds=10)
    controller._tick_countdown()
    assert not starts and not controller._countdown.isActive()
    window.close()


def test_auto_retry_waits_until_extra_file_review_closes(qtbot, monkeypatch, tmp_path):
    from mp3_playlist_downloader.ui import library_controller

    window = window_with_pending(qtbot, monkeypatch, tmp_path)
    controller = window.queue_controller
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    controller._clock = lambda: now
    starts = []
    monkeypatch.setattr(controller, "_start", lambda: starts.append(True))
    controller._arm_countdown(queue.PauseState("rate_limited", (now + timedelta(seconds=1)).isoformat(), 1))
    def review(dialog):
        controller._clock = lambda: now + timedelta(seconds=2)
        controller._tick_countdown()
        assert not starts
    monkeypatch.setattr(library_controller.ExtraFilesDialog, "exec", review)
    window.library_controller.review()
    controller._tick_countdown()
    assert starts == [True]
    controller.hide_banner()
    window.close()


def test_three_failed_auto_retries_require_manual_resume(qtbot, monkeypatch, tmp_path):
    from mp3_playlist_downloader.youtube.errors import RateLimitedError

    window = window_with_pending(qtbot, monkeypatch, tmp_path)
    controller = window.queue_controller
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    controller._clock = lambda: base + timedelta(hours=2)
    controller._countdown.setInterval(1)
    original = queue.run_queue
    attempts = []
    def limited(*args, **kwargs):
        attempts.append(True)
        raise RateLimitedError("limited")
    monkeypatch.setattr(queue, "run_queue", lambda connection, settings, **kwargs: original(connection, settings, download=limited, clock=lambda: base, **kwargs))
    controller.resume()
    qtbot.waitUntil(lambda: len(attempts) == 4 and not window.queue_running and "resume manually" in controller.banner.text(), timeout=5000)
    connection = db.connect()
    assert queue.pause_state(connection).streak == 4 and queue.pending_count(connection) == 1
    connection.close()
    window.settings.auto_resume_after_rate_limit = False
    qtbot.waitUntil(lambda: not window.library_controller.scans, timeout=5000)
    controller.resume()
    qtbot.waitUntil(lambda: len(attempts) == 5 and not window.queue_running, timeout=5000)
    connection = db.connect()
    assert queue.pause_state(connection).streak == 1
    connection.close()
    controller.hide_banner()
    window.close()
