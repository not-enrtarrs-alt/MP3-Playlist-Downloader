import sqlite3

import pytest

from mp3_playlist_downloader import db as db_module
from mp3_playlist_downloader.db import add_playlist, connect, initialize, list_playlists, list_videos, refresh_playlist, remove_playlist
from mp3_playlist_downloader.models import PlaylistMetadata, VideoMetadata


def test_schema_idempotent_and_pragmas(tmp_path):
    db = connect(tmp_path / "app.db")
    initialize(db)
    initialize(db)
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert db.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert dict(db.execute("SELECT key, value FROM meta")) == {
        "schema_version": "2", "queue_paused_until": "", "queue_pause_reason": "", "queue_rate_limit_streak": "0"
    }
    db.close()


def test_cross_playlist_duplicate_and_cascade(tmp_path):
    db = connect(tmp_path / "app.db")
    initialize(db)
    with db:
        for i in (1, 2):
            db.execute("INSERT INTO playlists(url,title,folder_path,added_at,updated_at) VALUES (?,?,?,?,?)", (str(i), "a", str(i), "utc", "utc"))
            db.execute("INSERT INTO videos(playlist_id,video_id,title,created_at,updated_at) VALUES (?,?,?,?,?)", (i, "same", "title", "utc", "utc"))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO videos(playlist_id,video_id,title,created_at,updated_at) VALUES (?,?,?,?,?)", (1, "same", "title", "utc", "utc"))
        db.execute("DELETE FROM playlists WHERE id=?", (1,))
    assert db.execute("SELECT playlist_id FROM videos").fetchone()[0] == 2
    db.close()


def test_newer_schema_is_not_overwritten(tmp_path):
    db = connect(tmp_path / "app.db")
    initialize(db)
    db.execute("UPDATE meta SET value=? WHERE key=?", ("99", "schema_version"))
    db.commit()
    with pytest.raises(RuntimeError):
        initialize(db)
    assert db.execute("SELECT value FROM meta WHERE key=?", ("schema_version",)).fetchone()[0] == "99"
    db.close()


def test_v1_migration_preserves_rows_and_refresh_preserves_override(tmp_path):
    connection = connect(tmp_path / "app.db")
    old_schema = db_module._SCHEMA.replace("    custom_title TEXT,\n", "")
    connection.executescript(old_schema)
    connection.execute("INSERT INTO meta(key,value) VALUES (?,?)", ("schema_version", "1"))
    connection.commit()
    pid, _ = add_playlist(connection, "canonical", PlaylistMetadata("Original", (VideoMetadata("aaaaaaaaaaa", "Old raw"),)), tmp_path / "out")
    existing = tmp_path / "out" / "Original" / "song.mp3"
    existing.write_bytes(b"unchanged")
    with connection:
        connection.execute("UPDATE videos SET downloaded=1,equalized=1,file_path=?,file_size=9,download_state='queued',attempts=2 WHERE playlist_id=?", (str(existing), pid))
    initialize(connection)
    initialize(connection)
    row = list_videos(connection, pid)[0]
    assert row["custom_title"] is None and row["title"] == "Old raw"
    assert (row["downloaded"], row["equalized"], row["file_path"], row["attempts"], row["download_state"]) == (1, 1, str(existing), 2, "queued")
    assert existing.read_bytes() == b"unchanged"
    with connection:
        connection.execute("UPDATE videos SET custom_title=? WHERE id=?", ("My title", row["id"]))
    refresh_playlist(connection, pid, PlaylistMetadata("Original", (VideoMetadata("aaaaaaaaaaa", "New raw"),)))
    row = list_videos(connection, pid)[0]
    assert row["title"] == "New raw" and row["custom_title"] == "My title"
    assert connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "2"
    connection.close()


def test_v1_migration_rolls_back_schema_if_version_update_fails(tmp_path):
    connection = connect(tmp_path / "app.db")
    old_schema = db_module._SCHEMA.replace("    custom_title TEXT,\n", "")
    connection.executescript(old_schema)
    connection.execute("INSERT INTO meta(key,value) VALUES (?,?)", ("schema_version", "1"))
    connection.execute("CREATE TRIGGER deny_migration BEFORE UPDATE ON meta BEGIN SELECT RAISE(ABORT, 'blocked'); END")
    connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        initialize(connection)
    assert "custom_title" not in {row["name"] for row in connection.execute("PRAGMA table_info(videos)")}
    assert connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "1"
    connection.close()


def test_add_refresh_preserves_downloads_and_removes_absent(tmp_path):
    db = connect(tmp_path / "app.db")
    initialize(db)
    first = PlaylistMetadata("Original", (VideoMetadata("aaaaaaaaaaa", "Old"), VideoMetadata("bbbbbbbbbbb", "Existing", position=1)))
    pid, added = add_playlist(db, "canonical", first, tmp_path / "out")
    assert added and add_playlist(db, "canonical", first, tmp_path / "out") == (pid, False)
    folder = tmp_path / "out" / "Original"
    assert folder.is_dir()
    with db:
        db.execute("UPDATE videos SET downloaded=1,equalized=1,file_path=?,file_size=9,attempts=2,download_state='queued' WHERE video_id=?", (str(folder / "song.mp3"), "bbbbbbbbbbb"))
    refreshed = PlaylistMetadata("Renamed", (VideoMetadata("bbbbbbbbbbb", "Updated"), VideoMetadata("ccccccccccc", "New", position=1)))
    refresh_playlist(db, pid, refreshed)
    rows = {row["video_id"]: row for row in list_videos(db, pid)}
    assert rows["aaaaaaaaaaa"]["in_playlist"] == 0
    assert rows["bbbbbbbbbbb"]["title"] == "Updated"
    assert tuple(rows["bbbbbbbbbbb"][field] for field in ("downloaded", "equalized", "file_size", "attempts", "download_state")) == (1, 1, 9, 2, "queued")
    assert rows["ccccccccccc"]["in_playlist"] == 1
    playlist = list_playlists(db)[0]
    assert playlist["album_sync_pending"] == 1 and playlist["folder_path"] == str(folder)
    remove_playlist(db, pid)
    assert not list_playlists(db) and folder.exists()
    db.close()


def test_refresh_rolls_back_all_updates_on_failure(tmp_path, monkeypatch):
    db = connect(tmp_path / "app.db")
    initialize(db)
    pid, _ = add_playlist(db, "canonical", PlaylistMetadata("Original", (VideoMetadata("aaaaaaaaaaa", "Old"),)), tmp_path)
    def fail(*args):
        raise RuntimeError("simulated failure")
    monkeypatch.setattr("mp3_playlist_downloader.db._upsert_videos", fail)
    with pytest.raises(RuntimeError):
        refresh_playlist(db, pid, PlaylistMetadata("Changed", ()))
    assert list_videos(db, pid)[0]["in_playlist"] == 1
    assert list_playlists(db)[0]["title"] == "Original"
    db.close()
