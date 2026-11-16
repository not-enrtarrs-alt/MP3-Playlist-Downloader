"""Synchronous playlist facades; callers own their thread's DB connection."""

from __future__ import annotations

import sqlite3
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import db, equalizer, tagging
from .models import PlaylistMetadata
from .settings import Settings
from .youtube.client import fetch_playlist
from .youtube.errors import YouTubeError
from .youtube.parse import normalize_playlist_url

logger = logging.getLogger(__name__)

class OperationCancelled(Exception):
    """A fetch was cancelled before applying its result."""


def add_playlist(connection: sqlite3.Connection, url: str, settings: Settings,
                 *, fetch: Callable[[str, Settings], PlaylistMetadata] = fetch_playlist,
                 cancelled: Callable[[], bool] = lambda: False) -> tuple[int, bool]:
    url = normalize_playlist_url(url)
    existing = db.find_playlist(connection, url)
    if existing:
        return int(existing["id"]), False
    metadata = fetch(url, settings)
    if cancelled():
        raise OperationCancelled()
    if not metadata.videos:
        raise YouTubeError("This playlist has no videos.")
    return db.add_playlist(connection, url, metadata, Path(settings.output_root))


def refresh_playlist(connection: sqlite3.Connection, playlist_id: int, settings: Settings,
                     *, fetch: Callable[[str, Settings], PlaylistMetadata] = fetch_playlist,
                     cancelled: Callable[[], bool] = lambda: False) -> None:
    row = connection.execute("SELECT url FROM playlists WHERE id=?", (playlist_id,)).fetchone()
    if row is None:
        raise YouTubeError("Playlist no longer exists.")
    metadata = fetch(row["url"], settings)
    if cancelled():
        raise OperationCancelled()
    db.refresh_playlist(connection, playlist_id, metadata)


def equalize_tracks(connection: sqlite3.Connection, video_ids: list[int], settings: Settings,
                    *, cancelled: Callable[[], bool] = lambda: False,
                    progress: Callable[[int, int, str], None] | None = None) -> equalizer.EqualizeSummary:
    """Apply gain to eligible selected tracks sequentially, continuing on failure."""
    if not equalizer.discover(settings):
        raise equalizer.EqualizerMissing(equalizer.MISSING_MESSAGE)
    # Preserve selection order and never run a track twice.
    unique_ids = list(dict.fromkeys(video_ids))
    summary = equalizer.EqualizeSummary(total=len(unique_ids))
    for index, video_id in enumerate(unique_ids, start=1):
        if cancelled():
            summary.cancelled = True
            break
        row = connection.execute("SELECT id,title,file_path,downloaded,equalized FROM videos WHERE id=?", (video_id,)).fetchone()
        if row is None or not row["downloaded"] or row["equalized"] or not row["file_path"]:
            continue
        if progress:
            progress(index, len(unique_ids), row["title"])
        try:
            equalizer.apply(Path(row["file_path"]), settings)
        except equalizer.EqualizerError as error:
            with connection:
                connection.execute("UPDATE videos SET error_kind='equalize',last_error=?,updated_at=? WHERE id=?", (str(error)[:500], db.utc_now(), video_id))
            summary.failed += 1
            continue
        except Exception:
            with connection:
                connection.execute("UPDATE videos SET error_kind='equalize',last_error=?,updated_at=? WHERE id=?", ("Equalization failed.", db.utc_now(), video_id))
            summary.failed += 1
            continue
        with connection:
            connection.execute("""
                UPDATE videos SET equalized=1,
                    last_error=CASE WHEN error_kind='equalize' THEN NULL ELSE last_error END,
                    error_kind=CASE WHEN error_kind='equalize' THEN NULL ELSE error_kind END,
                    updated_at=? WHERE id=?
            """, (db.utc_now(), video_id))
        summary.succeeded += 1
    return summary


def link_file(connection: sqlite3.Connection, video_id: int, source: Path, settings: Settings, **kwargs):
    """Link a user-selected MP3 using the dedicated filesystem service."""
    from .linking import link_file as do_link
    return do_link(connection, video_id, source, settings, **kwargs)


def rename_track(connection: sqlite3.Connection, video_id: int, title: str, **kwargs):
    """Apply an explicit track-title override without changing the raw title."""
    from .renaming import rename_track as do_rename
    return do_rename(connection, video_id, title, **kwargs)


@dataclass
class AlbumSyncSummary:
    succeeded: int = 0
    failed: int = 0
    cancelled: bool = False
    stale: bool = False
    total: int = 0


def sync_album(connection: sqlite3.Connection, playlist_id: int, *,
               cancelled: Callable[[], bool] = lambda: False,
               progress: Callable[[int, int, str], None] | None = None) -> AlbumSyncSummary:
    """Retag only album fields; keep the pending flag on failure or title change."""
    playlist = connection.execute("SELECT title FROM playlists WHERE id=?", (playlist_id,)).fetchone()
    if playlist is None:
        raise ValueError("Playlist no longer exists.")
    title = playlist["title"]
    rows = connection.execute("SELECT title,file_path FROM videos WHERE playlist_id=? AND downloaded=1 ORDER BY position,id", (playlist_id,)).fetchall()
    summary = AlbumSyncSummary(total=len(rows))
    for index, row in enumerate(rows, start=1):
        if cancelled():
            summary.cancelled = True
            break
        if progress:
            progress(index, len(rows), row["title"])
        try:
            if not row["file_path"] or not Path(row["file_path"]).is_file():
                raise OSError("missing tracked file")
            tagging.retag_album(Path(row["file_path"]), title)
            summary.succeeded += 1
        except Exception:
            summary.failed += 1
    if not summary.failed and not summary.cancelled:
        with connection:
            cursor = connection.execute("UPDATE playlists SET album_sync_pending=0,updated_at=? WHERE id=? AND title=?", (db.utc_now(), playlist_id, title))
        summary.stale = not bool(cursor.rowcount)
    logger.info("Album sync for playlist %s: %s updated, %s failed", playlist_id, summary.succeeded, summary.failed)
    return summary
