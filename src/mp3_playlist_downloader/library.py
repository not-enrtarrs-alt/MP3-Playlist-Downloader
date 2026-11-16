"""Safe playlist-folder scanning and collision-free filename allocation."""

from __future__ import annotations

import os
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from send2trash import send2trash

from .db import utc_now
from .paths import sanitize_filename


def normalized_path(path: str | Path) -> str:
    """Compare paths according to Windows case and absolute-path semantics."""
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _file_exists(path: str | Path) -> bool:
    """Only treat a file as missing on actual absence, not on permission errors."""
    try:
        return stat.S_ISREG(os.stat(path).st_mode)
    except (FileNotFoundError, NotADirectoryError):
        return False


@dataclass(frozen=True)
class ScanResult:
    new_extra_ids: tuple[int, ...]
    pending_count: int
    missing_tracks: int


def scan_folder(connection: sqlite3.Connection, playlist_id: int) -> ScanResult:
    """Reconcile a playlist folder atomically; never delete or create files."""
    playlist = connection.execute("SELECT folder_path FROM playlists WHERE id=?", (playlist_id,)).fetchone()
    if playlist is None:
        raise ValueError("Playlist no longer exists.")
    folder = Path(playlist["folder_path"])
    folder_missing = False
    try:
        with os.scandir(folder) as entries:
            files = [Path(entry.path) for entry in entries if not entry.name.casefold().startswith(".tmp-") and entry.name.casefold().endswith(".mp3") and entry.is_file()]
    except FileNotFoundError:
        files = []
        folder_missing = True
    videos = connection.execute("SELECT id, file_path FROM videos WHERE playlist_id=? AND (file_path IS NOT NULL OR downloaded=1 OR equalized=1)", (playlist_id,)).fetchall()
    extras = connection.execute("SELECT id, file_path FROM extra_files WHERE playlist_id=?", (playlist_id,)).fetchall()
    # Gather all filesystem state before mutating DB. Errors (including access denied)
    # must not silently turn inaccessible files into missing files.
    missing_videos = [row for row in videos if folder_missing or not row["file_path"] or not _file_exists(row["file_path"])]
    tracked_paths = {normalized_path(row["file_path"]) for row in videos if row["file_path"]}
    missing_extras = [row for row in extras if folder_missing or normalized_path(row["file_path"]) in tracked_paths or not _file_exists(row["file_path"])]
    known = {normalized_path(row["file_path"]) for row in videos + extras if row["file_path"]}
    discovered = sorted((path for path in files if normalized_path(path) not in known), key=lambda path: path.name.casefold())
    sizes = [(path, path.stat().st_size) for path in discovered]
    now = utc_now()
    new_ids: list[int] = []
    with connection:
        for row in missing_videos:
            connection.execute("UPDATE videos SET downloaded=0,equalized=0,file_path=NULL,file_size=NULL,updated_at=? WHERE id=?", (now, row["id"]))
        for row in missing_extras:
            connection.execute("DELETE FROM extra_files WHERE id=?", (row["id"],))
        for path, size in sizes:
            cursor = connection.execute("INSERT OR IGNORE INTO extra_files(playlist_id,file_path,file_name,size_bytes,disposition,discovered_at,updated_at) VALUES (?,?,?,?,?,?,?)", (playlist_id, str(path), path.name, size, "pending", now, now))
            if cursor.rowcount:
                new_ids.append(int(cursor.lastrowid))
        pending = connection.execute("SELECT COUNT(*) FROM extra_files WHERE playlist_id=? AND disposition=?", (playlist_id, "pending")).fetchone()[0]
    return ScanResult(tuple(new_ids), int(pending), len(missing_videos))


def list_extras(connection: sqlite3.Connection, playlist_id: int) -> list[sqlite3.Row]:
    return connection.execute("SELECT * FROM extra_files WHERE playlist_id=? ORDER BY file_name COLLATE NOCASE, id", (playlist_id,)).fetchall()


def allocate_mp3_path(folder: Path, title: str, used_paths: Iterable[str | Path] = ()) -> Path:
    """Allocate a path without overwriting disk files or database-owned paths."""
    folder = Path(folder)
    used = {normalized_path(path).casefold() for path in used_paths}
    try:
        with os.scandir(folder) as entries:
            used.update(normalized_path(entry.path).casefold() for entry in entries)
    except FileNotFoundError:
        pass
    name = sanitize_filename(title)
    candidate = folder / (name + ".mp3")
    number = 2
    while normalized_path(candidate).casefold() in used:
        suffix = f" ({number})"
        candidate = folder / (name[:120 - len(suffix)].rstrip(". ") + suffix + ".mp3")
        number += 1
    return candidate


def keep_extra(connection: sqlite3.Connection, extra_id: int) -> None:
    """Record an explicit decision to keep an extra; never touch the file."""
    with connection:
        cursor = connection.execute("UPDATE extra_files SET disposition=?,updated_at=? WHERE id=?", ("kept", utc_now(), extra_id))
        if not cursor.rowcount:
            raise ValueError("Extra file no longer exists.")


def delete_extra(connection: sqlite3.Connection, extra_id: int, *, recycle=None) -> None:
    """Recycle an explicitly selected extra, refusing all tracked video paths."""
    row = connection.execute("SELECT file_path FROM extra_files WHERE id=?", (extra_id,)).fetchone()
    if row is None:
        raise ValueError("Extra file no longer exists.")
    target = normalized_path(row["file_path"])
    tracked = connection.execute("SELECT file_path FROM videos WHERE file_path IS NOT NULL").fetchall()
    if any(normalized_path(video["file_path"]) == target for video in tracked):
        raise ValueError("A tracked file cannot be deleted as an extra.")
    (recycle or send2trash)(row["file_path"])
    with connection:
        connection.execute("DELETE FROM extra_files WHERE id=?", (extra_id,))


def delete_track(connection: sqlite3.Connection, video_row_id: int, *, recycle=None) -> None:
    """Recycle a tracked file first; reset its DB state only after success."""
    row = connection.execute("SELECT file_path,download_state FROM videos WHERE id=?", (video_row_id,)).fetchone()
    if row is None:
        raise ValueError("Track no longer exists.")
    if row["download_state"] == "downloading":
        raise ValueError("A track being downloaded cannot be deleted.")
    if row["file_path"]:
        (recycle or send2trash)(row["file_path"])
    with connection:
        connection.execute("""
            UPDATE videos SET downloaded=0,equalized=0,file_path=NULL,file_size=NULL,
                download_state='idle',attempts=0,error_kind=NULL,last_error=NULL,updated_at=? WHERE id=?
        """, (utc_now(), video_row_id))
