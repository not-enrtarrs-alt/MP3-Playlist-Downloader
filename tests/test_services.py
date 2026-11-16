import pytest

from mp3_playlist_downloader import db, services
from mp3_playlist_downloader.models import PlaylistMetadata, VideoMetadata
from mp3_playlist_downloader.settings import Settings
from mp3_playlist_downloader.youtube.errors import RateLimitedError, YouTubeError


@pytest.fixture
def store(tmp_path):
    connection = db.connect(tmp_path / "app.db")
    db.initialize(connection)
    yield connection
    connection.close()


def test_add_and_dedup_does_not_fetch_again(store, tmp_path):
    settings = Settings(output_root=str(tmp_path / "music"))
    calls = []
    def fetch(url, settings):
        calls.append(url)
        return PlaylistMetadata("Playlist", (VideoMetadata("aaaaaaaaaaa", "Song"),))
    first = services.add_playlist(store, "youtube.com/watch?v=x&list=PL123", settings, fetch=fetch)
    second = services.add_playlist(store, "https://music.youtube.com/playlist?list=PL123", settings, fetch=fetch)
    assert first == (second[0], True) and second[1] is False and len(calls) == 1


def test_add_empty_or_cancelled_never_persists(store, tmp_path):
    settings = Settings(output_root=str(tmp_path / "music"))
    with pytest.raises(YouTubeError):
        services.add_playlist(store, "youtube.com/?list=PL123", settings, fetch=lambda *_: PlaylistMetadata("Empty", ()))
    with pytest.raises(services.OperationCancelled):
        services.add_playlist(store, "youtube.com/?list=PL123", settings, fetch=lambda *_: PlaylistMetadata("Playlist", (VideoMetadata("aaaaaaaaaaa", "Song"),)), cancelled=lambda: True)
    assert not db.list_playlists(store)


def test_rate_limited_refresh_does_not_change_rows(store, tmp_path):
    settings = Settings(output_root=str(tmp_path / "music"))
    pid, _ = db.add_playlist(store, "https://www.youtube.com/playlist?list=PL123", PlaylistMetadata("Original", (VideoMetadata("aaaaaaaaaaa", "Song"),)), tmp_path)
    def limited(*args):
        raise RateLimitedError("limited")
    with pytest.raises(RateLimitedError):
        services.refresh_playlist(store, pid, settings, fetch=limited)
    assert db.list_playlists(store)[0]["title"] == "Original"
    assert db.list_videos(store, pid)[0]["in_playlist"] == 1


def test_equalize_selected_only_success_marked_and_failures_continue(store, tmp_path, monkeypatch):
    from mp3_playlist_downloader import equalizer

    settings = Settings(output_root=str(tmp_path / "music"))
    videos = tuple(VideoMetadata(f"video{i:06}", f"Song {i}", position=i) for i in range(4))
    pid, _ = db.add_playlist(store, "url", PlaylistMetadata("Playlist", videos), tmp_path)
    rows = db.list_videos(store, pid)
    for index, row in enumerate(rows[:3]):
        path = tmp_path / f"{index}.mp3"
        path.write_bytes(b"audio")
        with store:
            store.execute("UPDATE videos SET downloaded=1,file_path=?,equalized=? WHERE id=?", (str(path), int(index == 2), row["id"]))
    monkeypatch.setattr(equalizer, "discover", lambda settings: "fake-mp3gain")
    calls = []
    def apply(path, settings):
        calls.append(path.name)
        if path.name == "0.mp3":
            raise equalizer.EqualizerError("gain failed")
    monkeypatch.setattr(equalizer, "apply", apply)
    summary = services.equalize_tracks(store, [row["id"] for row in rows] + [rows[1]["id"]], settings)
    assert (summary.succeeded, summary.failed) == (1, 1)
    assert calls == ["0.mp3", "1.mp3"]
    updated = db.list_videos(store, pid)
    assert updated[0]["equalized"] == 0 and updated[0]["error_kind"] == "equalize"
    assert updated[1]["equalized"] == updated[2]["equalized"] == 1
    assert updated[3]["equalized"] == 0


def test_equalize_missing_binary_never_changes_state(store, tmp_path, monkeypatch):
    from mp3_playlist_downloader import equalizer

    pid, _ = db.add_playlist(store, "url", PlaylistMetadata("Playlist", (VideoMetadata("aaaaaaaaaaa", "Song"),)), tmp_path)
    row = db.list_videos(store, pid)[0]
    monkeypatch.setattr(equalizer, "discover", lambda settings: None)
    with pytest.raises(equalizer.EqualizerMissing):
        services.equalize_tracks(store, [row["id"]], Settings())
    assert db.list_videos(store, pid)[0]["equalized"] == 0


def test_equalize_cancel_between_tracks(store, tmp_path, monkeypatch):
    from mp3_playlist_downloader import equalizer
    pid, _ = db.add_playlist(store, "url", PlaylistMetadata("Playlist", (VideoMetadata("aaaaaaaaaaa", "A"), VideoMetadata("bbbbbbbbbbb", "B"))), tmp_path)
    rows = db.list_videos(store, pid)
    for row in rows:
        with store:
            store.execute("UPDATE videos SET downloaded=1,file_path=? WHERE id=?", (str(tmp_path / row["video_id"]), row["id"]))
    monkeypatch.setattr(equalizer, "discover", lambda settings: "fake")
    calls = []
    monkeypatch.setattr(equalizer, "apply", lambda path, settings: calls.append(path))
    summary = services.equalize_tracks(store, [row["id"] for row in rows], Settings(), cancelled=lambda: len(calls) > 0)
    assert summary.cancelled and summary.succeeded == 1
    assert [row["equalized"] for row in db.list_videos(store, pid)] == [1, 0]


def test_album_sync_preserves_other_frames(store, tmp_path, silent_mp3):
    import shutil
    from mutagen.id3 import ID3, TXXX
    from mp3_playlist_downloader import tagging

    pid, _ = db.add_playlist(store, "url", PlaylistMetadata("Old", (VideoMetadata("aaaaaaaaaaa", "Song"),)), tmp_path)
    path = tmp_path / "song.mp3"
    shutil.copyfile(silent_mp3, path)
    tagging.tag_file(path, "Song", "Artist", "Old")
    tags = ID3(path)
    tags.add(TXXX(encoding=3, desc="Custom", text="keep"))
    tags.save(path, v2_version=3)
    with store:
        store.execute("UPDATE videos SET downloaded=1,file_path=? WHERE playlist_id=?", (str(path), pid))
        store.execute("UPDATE playlists SET title='New',album_sync_pending=1 WHERE id=?", (pid,))
    summary = services.sync_album(store, pid)
    tags = ID3(path)
    assert summary.succeeded == 1 and summary.failed == 0
    assert str(tags["TALB"]) == "New" and str(tags["TIT2"]) == "Song" and tags.getall("TXXX")[0].text == ["keep"]
    assert db.list_playlists(store)[0]["album_sync_pending"] == 0


def test_album_sync_partial_failure_and_changed_title_stay_pending(store, tmp_path, monkeypatch):
    from mp3_playlist_downloader import tagging
    pid, _ = db.add_playlist(store, "url", PlaylistMetadata("New", (VideoMetadata("aaaaaaaaaaa", "A"), VideoMetadata("bbbbbbbbbbb", "B"))), tmp_path)
    for name in ("aaaaaaaaaaa", "bbbbbbbbbbb"):
        (tmp_path / name).write_bytes(b"fixture")
    with store:
        for row in db.list_videos(store, pid):
            store.execute("UPDATE videos SET downloaded=1,file_path=? WHERE id=?", (str(tmp_path / row["video_id"]), row["id"]))
        store.execute("UPDATE playlists SET album_sync_pending=1 WHERE id=?", (pid,))
    def failing(path, album):
        if path.name == "aaaaaaaaaaa":
            raise OSError("cannot tag")
    monkeypatch.setattr(tagging, "retag_album", failing)
    result = services.sync_album(store, pid)
    assert (result.succeeded, result.failed) == (1, 1)
    assert db.list_playlists(store)[0]["album_sync_pending"] == 1
    def rename(path, album):
        with store:
            store.execute("UPDATE playlists SET title='Newest',album_sync_pending=1 WHERE id=?", (pid,))
    monkeypatch.setattr(tagging, "retag_album", rename)
    result = services.sync_album(store, pid)
    assert result.stale and db.list_playlists(store)[0]["album_sync_pending"] == 1
