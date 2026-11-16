from pathlib import Path

import pytest

from mp3_playlist_downloader import db, library
from mp3_playlist_downloader.models import PlaylistMetadata, VideoMetadata


@pytest.fixture
def playlist(tmp_path):
    connection = db.connect(tmp_path / "app.db")
    db.initialize(connection)
    pid, _ = db.add_playlist(connection, "url", PlaylistMetadata("Playlist", (VideoMetadata("aaaaaaaaaaa", "Song"),)), tmp_path / "music")
    folder = tmp_path / "music" / "Playlist"
    yield connection, pid, folder
    connection.close()


def test_scan_detects_extras_ignores_tmp_and_reconciles_missing(playlist):
    connection, pid, folder = playlist
    tracked = folder / "tracked.mp3"
    tracked.write_bytes(b"audio")
    (folder / "Unexpected.MP3").write_bytes(b"extra")
    (folder / ".tmp-ignore.mp3").write_bytes(b"partial")
    (folder / "other.txt").write_bytes(b"text")
    (folder / "subfolder.mp3").mkdir()
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,equalized=1,file_path=?,file_size=5 WHERE playlist_id=?", (str(tracked), pid))
    result = library.scan_folder(connection, pid)
    assert len(result.new_extra_ids) == 1 and result.pending_count == 1
    assert library.list_extras(connection, pid)[0]["file_name"] == "Unexpected.MP3"
    assert not library.scan_folder(connection, pid).new_extra_ids
    tracked.unlink()
    result = library.scan_folder(connection, pid)
    row = db.list_videos(connection, pid)[0]
    assert result.missing_tracks == 1
    assert (row["downloaded"], row["equalized"], row["file_path"], row["file_size"]) == (0, 0, None, None)
    assert (folder / "Unexpected.MP3").exists()


def test_scan_preserves_kept_then_removes_missing_extra(playlist):
    connection, pid, folder = playlist
    extra = folder / "extra.mp3"
    extra.write_bytes(b"audio")
    extra_id = library.scan_folder(connection, pid).new_extra_ids[0]
    with connection:
        connection.execute("UPDATE extra_files SET disposition=? WHERE id=?", ("kept", extra_id))
    assert library.scan_folder(connection, pid).pending_count == 0
    assert library.list_extras(connection, pid)[0]["disposition"] == "kept"
    extra.unlink()
    library.scan_folder(connection, pid)
    assert library.list_extras(connection, pid) == []


def test_missing_folder_does_not_recreate_it(playlist):
    connection, pid, folder = playlist
    folder.rmdir()
    result = library.scan_folder(connection, pid)
    assert result.pending_count == 0 and not folder.exists()


def test_allocation_case_insensitive_and_preserves_unrelated(playlist):
    connection, pid, folder = playlist
    original = folder / "Song.MP3"
    original.write_bytes(b"do not overwrite")
    second = folder / "Song (2).mp3"
    assert library.allocate_mp3_path(folder, "song", [second]).name == "song (3).mp3"
    assert original.read_bytes() == b"do not overwrite"


def test_scan_permission_error_does_not_change_state(playlist, monkeypatch):
    connection, pid, folder = playlist
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,equalized=1,file_path=? WHERE playlist_id=?", (str(folder / "tracked.mp3"), pid))
    def denied(*args):
        raise PermissionError("access denied")
    monkeypatch.setattr(library.os, "scandir", denied)
    with pytest.raises(PermissionError):
        library.scan_folder(connection, pid)
    row = db.list_videos(connection, pid)[0]
    assert row["downloaded"] == row["equalized"] == 1


def test_keep_and_explicit_extra_delete(playlist):
    connection, pid, folder = playlist
    path = folder / "extra.mp3"
    path.write_bytes(b"data")
    extra_id = library.scan_folder(connection, pid).new_extra_ids[0]
    library.keep_extra(connection, extra_id)
    assert library.list_extras(connection, pid)[0]["disposition"] == "kept"
    calls = []
    library.delete_extra(connection, extra_id, recycle=calls.append)
    assert calls == [str(path)] and library.list_extras(connection, pid) == []
    assert path.exists()  # fake recycler did not touch the file


def test_delete_extra_refuses_any_tracked_path(playlist):
    connection, pid, folder = playlist
    path = folder / "extra.mp3"
    path.write_bytes(b"data")
    extra_id = library.scan_folder(connection, pid).new_extra_ids[0]
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,file_path=? WHERE playlist_id=?", (str(path), pid))
    calls = []
    with pytest.raises(ValueError, match="tracked"):
        library.delete_extra(connection, extra_id, recycle=calls.append)
    assert not calls and len(library.list_extras(connection, pid)) == 1


def test_delete_track_recycle_failure_preserves_db(playlist):
    connection, pid, folder = playlist
    path = folder / "track.mp3"
    path.write_bytes(b"audio")
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,equalized=1,file_path=?,file_size=5,attempts=2,download_state='failed',error_kind='other',last_error='error' WHERE playlist_id=?", (str(path), pid))
    vid = db.list_videos(connection, pid)[0]["id"]
    def fail(path):
        raise OSError("recycle failed")
    with pytest.raises(OSError):
        library.delete_track(connection, vid, recycle=fail)
    assert db.list_videos(connection, pid)[0]["downloaded"] == 1
    calls = []
    library.delete_track(connection, vid, recycle=calls.append)
    row = db.list_videos(connection, pid)[0]
    assert calls == [str(path)]
    assert (row["downloaded"], row["equalized"], row["file_path"], row["download_state"], row["attempts"], row["last_error"]) == (0, 0, None, "idle", 0, None)


def test_extra_recycle_failure_keeps_row(playlist):
    connection, pid, folder = playlist
    (folder / "extra.mp3").write_bytes(b"data")
    extra_id = library.scan_folder(connection, pid).new_extra_ids[0]
    def fail(path):
        raise OSError("recycle failed")
    with pytest.raises(OSError):
        library.delete_extra(connection, extra_id, recycle=fail)
    assert len(library.list_extras(connection, pid)) == 1


def test_scan_removes_extra_record_after_track_adoption_without_deleting(playlist):
    connection, pid, folder = playlist
    path = folder / "extra.mp3"
    path.write_bytes(b"audio")
    library.scan_folder(connection, pid)
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,file_path=? WHERE playlist_id=?", (str(path), pid))
    library.scan_folder(connection, pid)
    assert not library.list_extras(connection, pid)
    assert path.read_bytes() == b"audio"


def test_scan_clears_invalid_download_with_no_path(playlist):
    connection, pid, folder = playlist
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,equalized=1,file_path=NULL WHERE playlist_id=?", (pid,))
    assert library.scan_folder(connection, pid).missing_tracks == 1
    row = db.list_videos(connection, pid)[0]
    assert not row["downloaded"] and not row["equalized"]
