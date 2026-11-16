"""SQLite connections and idempotent schema initialization."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import PlaylistMetadata
from .paths import db_path, playlist_folder

logger = logging.getLogger(__name__)
SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    folder_path TEXT NOT NULL UNIQUE,
    album_sync_pending INTEGER NOT NULL DEFAULT 0,
    added_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_refreshed_at TEXT
);
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    video_id TEXT NOT NULL,
    title TEXT NOT NULL,
    custom_title TEXT,
    uploader TEXT,
    duration_seconds INTEGER,
    thumbnail_url TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    in_playlist INTEGER NOT NULL DEFAULT 1,
    unavailable INTEGER NOT NULL DEFAULT 0,
    is_topic INTEGER NOT NULL DEFAULT 0,
    downloaded INTEGER NOT NULL DEFAULT 0,
    equalized INTEGER NOT NULL DEFAULT 0,
    file_path TEXT,
    file_size INTEGER,
    download_state TEXT NOT NULL DEFAULT 'idle',
    attempts INTEGER NOT NULL DEFAULT 0,
    error_kind TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (playlist_id, video_id)
);
CREATE TABLE IF NOT EXISTS extra_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    size_bytes INTEGER,
    disposition TEXT NOT NULL DEFAULT 'pending',
    discovered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (playlist_id, file_path)
);
CREATE INDEX IF NOT EXISTS idx_videos_playlist ON videos(playlist_id, position);
CREATE INDEX IF NOT EXISTS idx_videos_state ON videos(playlist_id, download_state);
CREATE INDEX IF NOT EXISTS idx_extra_playlist ON extra_files(playlist_id, disposition);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Create a new connection owned by the calling thread."""
    path = path or db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        if connection.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
            connection.execute("PRAGMA journal_mode=WAL")
    except Exception:
        connection.close()
        raise
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    """Initialize or migrate to schema 2, rejecting unsupported versions."""
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", ("meta",)).fetchone()
    version = None
    if exists:
        row = connection.execute("SELECT value FROM meta WHERE key=?", ("schema_version",)).fetchone()
        version = row[0] if row is not None else None
        if version not in (None, "1", str(SCHEMA_VERSION)):
            raise RuntimeError("Unsupported database schema version.")
    connection.executescript(_SCHEMA)
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(videos)")}
        if "custom_title" not in columns:
            if version == str(SCHEMA_VERSION):
                raise RuntimeError("Database schema is missing the custom-title column.")
            connection.execute("ALTER TABLE videos ADD COLUMN custom_title TEXT")
        connection.executemany("INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)", [
            ("schema_version", str(SCHEMA_VERSION)),
            ("queue_paused_until", ""),
            ("queue_pause_reason", ""),
            ("queue_rate_limit_streak", "0"),
        ])
        if version == "1":
            connection.execute("UPDATE meta SET value=? WHERE key=?", (str(SCHEMA_VERSION), "schema_version"))
    logger.info("Database schema initialized at version %s", SCHEMA_VERSION)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_playlist(connection: sqlite3.Connection, url: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM playlists WHERE url=?", (url,)).fetchone()


def list_playlists(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute("""
        SELECT p.*, COUNT(v.id) AS track_count,
               COALESCE(SUM(v.downloaded), 0) AS downloaded_count
        FROM playlists p LEFT JOIN videos v ON v.playlist_id=p.id
        GROUP BY p.id ORDER BY p.id
    """).fetchall()


def list_videos(connection: sqlite3.Connection, playlist_id: int) -> list[sqlite3.Row]:
    return connection.execute("SELECT * FROM videos WHERE playlist_id=? ORDER BY in_playlist DESC, position, id", (playlist_id,)).fetchall()


def _upsert_videos(connection: sqlite3.Connection, playlist_id: int, metadata: PlaylistMetadata, now: str) -> None:
    for video in metadata.videos:
        connection.execute("""
            INSERT INTO videos (playlist_id, video_id, title, uploader, duration_seconds,
                                thumbnail_url, position, unavailable, is_topic, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(playlist_id, video_id) DO UPDATE SET
                title=excluded.title, uploader=excluded.uploader,
                duration_seconds=excluded.duration_seconds, thumbnail_url=excluded.thumbnail_url,
                position=excluded.position, unavailable=excluded.unavailable,
                is_topic=excluded.is_topic, in_playlist=1, updated_at=excluded.updated_at
        """, (playlist_id, video.video_id, video.title, video.uploader, video.duration_seconds,
              video.thumbnail_url, video.position, int(video.unavailable), int(video.is_topic), now, now))


def add_playlist(connection: sqlite3.Connection, url: str, metadata: PlaylistMetadata, root: Path) -> tuple[int, bool]:
    """Insert a complete playlist in one transaction, or return the existing ID."""
    with connection:
        existing = find_playlist(connection, url)
        if existing:
            return int(existing["id"]), False
        used_paths = (row[0] for row in connection.execute("SELECT folder_path FROM playlists"))
        folder = playlist_folder(root, metadata.title, used_paths)
        # Never remove a pre-existing folder; its files will later be scanned as extras.
        folder.mkdir(parents=True, exist_ok=True)
        now = utc_now()
        cursor = connection.execute("INSERT INTO playlists(url,title,folder_path,added_at,updated_at,last_refreshed_at) VALUES (?,?,?,?,?,?)", (url, metadata.title, str(folder), now, now, now))
        playlist_id = int(cursor.lastrowid)
        _upsert_videos(connection, playlist_id, metadata, now)
    logger.info("Added playlist %s with %s videos", playlist_id, len(metadata.videos))
    return playlist_id, True


def refresh_playlist(connection: sqlite3.Connection, playlist_id: int, metadata: PlaylistMetadata) -> None:
    """Atomically refresh metadata while retaining every download-related field."""
    now = utc_now()
    with connection:
        playlist = connection.execute("SELECT title FROM playlists WHERE id=?", (playlist_id,)).fetchone()
        if playlist is None:
            raise ValueError("Playlist no longer exists.")
        connection.execute("UPDATE videos SET in_playlist=0, updated_at=? WHERE playlist_id=?", (now, playlist_id))
        _upsert_videos(connection, playlist_id, metadata, now)
        connection.execute("""
            UPDATE playlists SET title=?, album_sync_pending=CASE WHEN title<>? THEN 1 ELSE album_sync_pending END,
            updated_at=?, last_refreshed_at=? WHERE id=?
        """, (metadata.title, metadata.title, now, now, playlist_id))
    logger.info("Refreshed playlist %s with %s videos", playlist_id, len(metadata.videos))


def remove_playlist(connection: sqlite3.Connection, playlist_id: int) -> None:
    """Remove DB records only; leave all user files in place."""
    with connection:
        connection.execute("DELETE FROM playlists WHERE id=?", (playlist_id,))
    logger.info("Removed playlist %s from database; files preserved", playlist_id)
