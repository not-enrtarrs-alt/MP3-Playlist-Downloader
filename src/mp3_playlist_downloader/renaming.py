"""Safe, explicit per-track title overrides and file renaming."""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import uuid4

from send2trash import send2trash

from . import db, library, tagging
from .paths import sanitize_filename
from .youtube.download import _publish_exclusive, _publish_path

logger = logging.getLogger(__name__)


class RenameError(Exception):
    """A safe-to-display failure without private file paths."""


class RenameCancelled(RenameError):
    pass


@dataclass(frozen=True)
class RenameResult:
    title: str
    file_path: Path | None
    warning: str | None = None


def _signature(path: Path) -> tuple[int, int, int, int]:
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _move_no_replace(source: Path, target: Path) -> None:
    """Move without overwriting, or leave the source in place on failure."""
    if os.name == "nt":
        os.rename(source, target)
        return
    os.link(source, target)
    try:
        source.unlink()
    except BaseException:
        # Both names remain available if the unlink fails; never delete either.
        raise


def _move_to_allocated(source: Path, folder: Path, title: str, used: list[str]) -> Path:
    while True:
        target = library.allocate_mp3_path(folder, title, used)
        try:
            _move_no_replace(source, target)
            return target
        except FileExistsError:
            used.append(str(target))


def _restore_original(backup: Path, original: Path, published: Path | None,
                      published_signature: tuple[int, int, int, int] | None,
                      original_signature: tuple[int, int, int, int], folder: Path, used: list[str]) -> bool:
    """Restore without replacing any new file; leave safe copies if blocked."""
    try:
        if backup.is_symlink() or _signature(backup) != original_signature:
            return False
        if published and library.normalized_path(published) == library.normalized_path(original) and published.exists():
            if published_signature is None or _signature(published) != published_signature:
                return False
            _move_to_allocated(published, folder, "Untracked rename copy - " + published.stem, used)
        _move_no_replace(backup, original)
        return True
    except OSError:
        return False


def rename_track(connection: sqlite3.Connection, video_id: int, title: str, *,
                 recycle: Callable[[str], None] | None = None,
                 cancelled: Callable[[], bool] = lambda: False) -> RenameResult:
    """Save an override and safely rename/retag a tracked MP3 if present."""
    title = title.strip()
    if not title or any(ord(char) < 32 or ord(char) == 127 for char in title):
        raise RenameError("Enter a non-empty title without control characters.")
    row = connection.execute("""
        SELECT v.*,p.folder_path FROM videos v JOIN playlists p ON p.id=v.playlist_id WHERE v.id=?
    """, (video_id,)).fetchone()
    if row is None:
        raise RenameError("Track no longer exists.")
    if row["download_state"] == "downloading":
        raise RenameError("A track being downloaded cannot be renamed.")
    if cancelled():
        raise RenameCancelled("Rename cancelled.")
    if not row["downloaded"]:
        try:
            with connection:
                cursor = connection.execute("UPDATE videos SET custom_title=?,updated_at=? WHERE id=? AND download_state<>'downloading'", (title, db.utc_now(), video_id))
                if not cursor.rowcount:
                    raise RenameError("Track changed; try again.")
        except sqlite3.Error:
            raise RenameError("The custom title could not be saved.") from None
        return RenameResult(title, None)
    if not row["file_path"]:
        raise RenameError("The tracked MP3 is missing; scan the folder first.")
    old, folder = Path(row["file_path"]), Path(row["folder_path"])
    if library.normalized_path(old.parent) != library.normalized_path(folder) or old.is_symlink() or not old.is_file():
        raise RenameError("The tracked MP3 is missing or outside its playlist folder.")
    others = connection.execute("SELECT file_path FROM videos WHERE id<>? AND file_path IS NOT NULL", (video_id,)).fetchall()
    if any(library.normalized_path(other["file_path"]).casefold() == library.normalized_path(old).casefold() for other in others):
        raise RenameError("The tracked file is shared by another track and cannot be renamed safely.")
    used = [item["file_path"] for item in others]
    used.extend(item["file_path"] for item in connection.execute("SELECT file_path FROM extra_files"))
    stage = folder / f".tmp-{uuid4().hex}.mp3"
    stage_created = False
    stage_identity: tuple[int, int] | None = None
    backup: Path | None = None
    published: Path | None = None
    published_signature = None
    try:
        snapshot = _signature(old)
        with old.open("rb") as source, stage.open("xb") as destination:
            stage_created = True
            stage_info = os.fstat(destination.fileno())
            stage_identity = (stage_info.st_dev, stage_info.st_ino)
            shutil.copyfileobj(source, destination)
        if _signature(old) != snapshot:
            raise RenameError("The tracked file changed; it was not renamed.")
        try:
            tagging.retag_title(stage, title)
        except Exception:
            raise RenameError("The MP3 title tag could not be updated; the original is unchanged.") from None
        if cancelled():
            raise RenameCancelled("Rename cancelled.")
        staged = stage.stat()
        if stage.is_symlink() or (staged.st_dev, staged.st_ino) != stage_identity:
            raise RenameError("The temporary rename file changed; the original is unchanged.")
        if _signature(old) != snapshot or old.is_symlink():
            raise RenameError("The tracked file changed; it was not renamed.")
        backup = _move_to_allocated(old, folder, "Original before rename - " + old.stem, used)
        desired = folder / (sanitize_filename(title) + ".mp3")
        if library.normalized_path(desired).casefold() == library.normalized_path(old).casefold():
            try:
                published = _publish_path(stage, desired)
            except FileExistsError:
                published = _publish_exclusive(stage, folder, title, used)
        else:
            published = _publish_exclusive(stage, folder, title, used)
        published_signature = _signature(published)
        with connection:
            cursor = connection.execute("""
                UPDATE videos SET custom_title=?,file_path=?,file_size=?,updated_at=?
                WHERE id=? AND downloaded=1 AND file_path=? AND updated_at=? AND download_state<>'downloading'
            """, (title, str(published), published.stat().st_size, db.utc_now(), video_id, row["file_path"], row["updated_at"]))
            if not cursor.rowcount:
                raise RenameError("Track changed while renaming; try again.")
    except Exception as error:
        if backup is not None:
            restored = _restore_original(backup, old, published, published_signature, snapshot, folder, used)
            if not restored:
                # If another file occupied the original path, keep the DB linked
                # to the preserved original rather than to an unrelated file.
                try:
                    if not backup.is_symlink() and _signature(backup) == snapshot:
                        with connection:
                            connection.execute("UPDATE videos SET file_path=?,file_size=?,updated_at=? WHERE id=? AND file_path=? AND downloaded=1", (str(backup), backup.stat().st_size, db.utc_now(), video_id, row["file_path"]))
                except (OSError, sqlite3.Error):
                    logger.warning("Could not update the preserved original's DB path for track row %s", video_id)
                raise RenameError("Rename failed. The original remains as an additional file in the playlist folder; review it before retrying.") from None
        if isinstance(error, RenameError):
            raise
        raise RenameError("The MP3 could not be renamed; the original was preserved.") from None
    finally:
        if stage_created:
            try:
                if stage.exists():
                    staged = stage.stat()
                    if not stage.is_symlink() and (staged.st_dev, staged.st_ino) == stage_identity:
                        stage.unlink()
                    else:
                        logger.warning("A temporary rename path changed; it was left untouched.")
            except OSError:
                logger.warning("Could not remove a temporary rename copy.")
    warning = None
    try:
        if backup is None or backup.is_symlink() or _signature(backup) != snapshot:
            raise OSError("Original backup changed")
        (recycle or send2trash)(str(backup))
    except Exception:
        warning = "The original was kept as an additional MP3 because it could not be recycled."
        logger.warning("Could not recycle the original after renaming track row %s", video_id)
    logger.info("Renamed track row %s", video_id)
    return RenameResult(title, published, warning)
