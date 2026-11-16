"""Safely link an explicitly selected MP3 to a playlist track."""

from __future__ import annotations

import os
import logging
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import uuid4

from send2trash import send2trash

from . import db, equalizer, library, paths, tagging
from .settings import Settings
from .youtube.download import _publish_exclusive, _tracked_snapshot
from .youtube.errors import YouTubeError

logger = logging.getLogger(__name__)


class LinkError(Exception):
    """A safe-to-display manual-link error."""


class LinkCancelled(LinkError):
    """A link was cancelled before recycling or publishing."""


@dataclass(frozen=True)
class LinkResult:
    file_path: Path
    equalized: bool
    warning: str | None = None


def link_file(connection: sqlite3.Connection, video_id: int, source: Path, settings: Settings,
              *, recycle: Callable[[str], None] | None = None,
              cover_loader: Callable | None = None,
              cancelled: Callable[[], bool] = lambda: False) -> LinkResult:
    """Copy external files or adopt an unlinked local extra; never mutate external sources."""
    row = connection.execute("""
        SELECT v.*,p.title AS playlist_title,p.folder_path FROM videos v
        JOIN playlists p ON p.id=v.playlist_id WHERE v.id=?
    """, (video_id,)).fetchone()
    if row is None:
        raise LinkError("Track no longer exists.")
    if row["download_state"] == "downloading":
        raise LinkError("A track being downloaded cannot be linked.")
    source = Path(source)
    if source.suffix.casefold() != ".mp3":
        raise LinkError("Choose a readable MP3 file.")
    try:
        with source.open("rb"):
            pass
        if not source.is_file():
            raise OSError("not a file")
        source_stat = source.stat()
    except (OSError, ValueError):
        raise LinkError("Choose a readable MP3 file.") from None
    folder = Path(row["folder_path"])
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise LinkError("The playlist folder is not writable.") from None
    video = dict(row)
    old_path = row["file_path"] if row["downloaded"] else None
    same_track = bool(old_path and library.normalized_path(old_path) == library.normalized_path(source))
    others = connection.execute("SELECT file_path FROM videos WHERE id<>? AND file_path IS NOT NULL", (video_id,)).fetchall()
    other_paths = {library.normalized_path(other["file_path"]) for other in others}
    if old_path and library.normalized_path(old_path) in other_paths:
        raise LinkError("The tracked file is shared by another video and cannot be replaced safely.")
    if same_track and (source.is_symlink() or source_stat.st_nlink > 1):
        raise LinkError("The tracked file is linked elsewhere and cannot be safely retagged in place.")
    try:
        old_snapshot = _tracked_snapshot(video, folder, bool(old_path and not same_track))
    except YouTubeError:
        raise LinkError("The existing tracked file is missing or outside the playlist folder.") from None
    inside = library.normalized_path(source.parent) == library.normalized_path(folder)
    adopt = inside and not same_track and library.normalized_path(source) not in other_paths and not source.is_symlink() and source_stat.st_nlink <= 1
    temporary: Path | None = None
    try:
        if cancelled():
            raise LinkCancelled("Link cancelled.")
        if same_track or adopt:
            target = source
        else:
            temporary = folder / f".tmp-{uuid4().hex}.mp3"
            with source.open("rb") as input_file, temporary.open("xb") as output_file:
                shutil.copyfileobj(input_file, output_file)
            target = temporary
        ffmpeg = paths.find_tool("ffmpeg", settings.ffmpeg_path)
        try:
            cover = (cover_loader or tagging.load_cover)(row["video_id"], None, ffmpeg)
            if same_track or adopt:
                current = source.stat()
                original = (source_stat.st_dev, source_stat.st_ino, source_stat.st_size, source_stat.st_mtime_ns)
                if source.is_symlink() or (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != original:
                    raise LinkError("The selected MP3 changed; it was not tagged.")
            tagging.tag_file(target, row["title"], row["uploader"], row["playlist_title"], cover, row["custom_title"])
        except LinkError:
            raise
        except Exception:
            raise LinkError("The selected MP3 could not be tagged.") from None
        equalized = False
        warning = None
        if settings.auto_equalize:
            try:
                equalizer.apply(target, settings)
                equalized = True
            except equalizer.EqualizerError as error:
                warning = str(error)[:500]
        if cancelled():
            raise LinkCancelled("Link cancelled.")
        if old_snapshot:
            try:
                current = _tracked_snapshot(video, folder, True)
                if current is None or current[1] != old_snapshot[1]:
                    raise LinkError("The existing tracked file changed; it was not replaced.")
                (recycle or send2trash)(str(old_snapshot[0]))
            except LinkError:
                raise
            except Exception:
                raise LinkError("The existing tracked file could not be moved to the Recycle Bin.") from None
        if temporary:
            used = [item[0] for item in connection.execute("SELECT file_path FROM videos WHERE playlist_id=? AND file_path IS NOT NULL UNION SELECT file_path FROM extra_files WHERE playlist_id=?", (row["playlist_id"], row["playlist_id"]))]
            target = _publish_exclusive(temporary, folder, row["custom_title"] or source.stem, used)
        target_size = target.stat().st_size
        with connection:
            if adopt:
                for extra in connection.execute("SELECT id,file_path FROM extra_files WHERE playlist_id=?", (row["playlist_id"],)).fetchall():
                    if library.normalized_path(extra["file_path"]) == library.normalized_path(target):
                        connection.execute("DELETE FROM extra_files WHERE id=?", (extra["id"],))
            connection.execute("""
                UPDATE videos SET downloaded=1,equalized=?,file_path=?,file_size=?,download_state='idle',attempts=0,
                    error_kind=?,last_error=?,updated_at=? WHERE id=?
            """, (int(equalized), str(target), target_size, "equalize" if warning else None, warning, db.utc_now(), video_id))
        logger.info("Linked MP3 to track row %s", video_id)
        return LinkResult(target, equalized, warning)
    except LinkError:
        raise
    except OSError:
        raise LinkError("The selected MP3 could not be linked. Check folder access.") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
