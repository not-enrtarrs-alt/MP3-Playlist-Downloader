"""One-at-a-time yt-dlp MP3 pipeline with exclusive destination creation."""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import uuid4

import yt_dlp
from send2trash import send2trash

from .. import equalizer, library, paths, tagging
from ..settings import Settings
from .client import _PrivateYtDlpLogger, cookie_options
from .errors import NetworkError, RateLimitedError, UnavailableError, YouTubeError, classify_error
from .parse import title_and_artist

logger = logging.getLogger(__name__)


class DownloadCancelled(Exception):
    pass


@dataclass(frozen=True)
class DownloadResult:
    file_path: Path
    file_size: int
    equalized: bool = False
    warning_kind: str | None = None
    warning: str | None = None


def _publish_path(source: Path, target: Path) -> Path:
    """Publish without replacing an existing path, even if another process races."""
    if os.name == "nt":
        os.rename(source, target)
        return target
    try:
        os.link(source, target)
    except FileExistsError:
        raise
    except OSError:
        pass
    else:
        source.unlink()
        return target
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o666)
    try:
        with os.fdopen(fd, "wb") as destination, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, destination)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def _publish_exclusive(source: Path, folder: Path, title: str, used_paths: Iterable[str | Path]) -> Path:
    """Allocate and publish atomically without replacing unrelated files."""
    used = list(used_paths)
    while True:
        target = library.allocate_mp3_path(folder, title, used)
        try:
            return _publish_path(source, target)
        except FileExistsError:
            used.append(target)


def _tracked_snapshot(video: dict[str, Any], folder: Path, overwrite: bool) -> tuple[Path, tuple] | None:
    if not overwrite or not video.get("downloaded"):
        return None
    raw = video.get("file_path")
    if not raw:
        raise YouTubeError("The tracked file is missing; scan the playlist folder first.")
    old = Path(raw)
    if library.normalized_path(old.parent) != library.normalized_path(folder) or old.is_symlink() or not old.is_file():
        raise YouTubeError("The tracked file is missing or outside its playlist folder.")
    info = old.stat()
    return old, (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def download_video(video: dict[str, Any], playlist_title: str, folder: Path, settings: Settings,
                   *, used_paths: Iterable[str | Path] = (), progress: Callable[[float, float | None, int | None], None] | None = None,
                   cancelled: Callable[[], bool] = lambda: False, downloader_factory: Callable[..., Any] | None = None,
                   cover_loader: Callable[..., bytes | None] | None = None, overwrite: bool = False,
                   recycle: Callable[[str], None] | None = None) -> DownloadResult:
    """Download, tag and publish one new MP3, never overwriting unrelated files."""
    ffmpeg = paths.find_tool("ffmpeg", settings.ffmpeg_path)
    if not ffmpeg:
        raise YouTubeError("ffmpeg not found. Install it or set its path in Settings → Tools.")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    tracked = _tracked_snapshot(video, folder, overwrite)
    base = folder / f".tmp-{uuid4().hex}"
    temporary_mp3 = base.with_suffix(".mp3")
    stage = {"audio_complete": False, "thumbnail_active": False}
    recovered_thumbnail = False

    def hook(status: dict[str, Any]) -> None:
        if cancelled():
            raise DownloadCancelled()
        if progress and status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            done = status.get("downloaded_bytes") or 0
            percent = min(100.0, 100.0 * done / total) if total else 0.0
            progress(percent, status.get("speed"), status.get("eta"))

    def postprocessor_hook(status: dict[str, Any]) -> None:
        if cancelled():
            raise DownloadCancelled()
        name, state = status.get("postprocessor"), status.get("status")
        if name == "ExtractAudio" and state == "finished":
            stage["audio_complete"] = True
        elif name == "ThumbnailsConvertor":
            stage["thumbnail_active"] = state == "started"

    options = {
        "format": "bestaudio/best",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"}, {"key": "FFmpegThumbnailsConvertor", "format": "jpg"}],
        "outtmpl": str(base) + ".%(ext)s", "noplaylist": True, "writethumbnail": True,
        "windowsfilenames": True, "quiet": True, "no_warnings": True, "progress_hooks": [hook],
        "postprocessor_hooks": [postprocessor_hook],
        "ffmpeg_location": ffmpeg, "logger": _PrivateYtDlpLogger(), **cookie_options(settings),
    }
    try:
        if cancelled():
            raise DownloadCancelled()
        try:
            with (downloader_factory or yt_dlp.YoutubeDL)(options) as downloader:
                downloader.extract_info(f"https://www.youtube.com/watch?v={video['video_id']}", download=True)
        except DownloadCancelled:
            raise
        except Exception as error:
            if cancelled():
                raise DownloadCancelled() from None
            classified = error if isinstance(error, YouTubeError) else classify_error(error)
            salvage = (stage["audio_complete"] and stage["thumbnail_active"]
                       and temporary_mp3.is_file() and temporary_mp3.stat().st_size > 0
                       and not isinstance(error, (RateLimitedError, UnavailableError, NetworkError)))
            if not salvage:
                raise classified from None
            recovered_thumbnail = True
            logger.warning("Thumbnail conversion failed after audio extraction; trying cover fallback.")
        if cancelled():
            raise DownloadCancelled()
        if not temporary_mp3.is_file() or temporary_mp3.stat().st_size == 0:
            raise YouTubeError("The downloaded MP3 was not created or was empty.")
        extensions = (".png", ".webp", ".jpg", ".jpeg") if recovered_thumbnail else (".jpg", ".jpeg", ".png", ".webp")
        thumbnail = next((base.with_suffix(ext) for ext in extensions if base.with_suffix(ext).is_file() and base.with_suffix(ext).stat().st_size > 0), None)
        warning_kind = warning = None
        try:
            cover = (cover_loader or tagging.load_cover)(video["video_id"], thumbnail, ffmpeg)
            tagging.tag_file(temporary_mp3, video["title"], video.get("uploader"), playlist_title, cover, video.get("custom_title"))
        except Exception:
            warning_kind, warning = "tag", "The MP3 was downloaded, but its tags could not be written."
            logger.warning("Tagging failed; preserving downloaded audio.")
        equalized = False
        if settings.auto_equalize:
            try:
                equalizer.apply(temporary_mp3, settings)
                equalized = True
            except equalizer.EqualizerError as error:
                equalize_warning = str(error)
                if warning_kind is None:
                    warning_kind, warning = "equalize", equalize_warning
                else:
                    warning = f"{warning} {equalize_warning}"[:500]
                logger.warning("Automatic equalization failed; preserving downloaded audio.")
        if cancelled():
            raise DownloadCancelled()
        display_title, _ = title_and_artist(video["title"], video.get("uploader"), video.get("custom_title"))
        if tracked:
            old, previous = tracked
            current = _tracked_snapshot(video, folder, True)
            if current is None or current[1] != previous:
                raise YouTubeError("The tracked file changed during download; it was not replaced.")
            (recycle or send2trash)(str(old))
            try:
                target = _publish_path(temporary_mp3, old)
            except FileExistsError:
                target = _publish_exclusive(temporary_mp3, folder, display_title, used_paths)
        else:
            target = _publish_exclusive(temporary_mp3, folder, display_title, used_paths)
        logger.info("Downloaded one MP3.")
        return DownloadResult(target, target.stat().st_size, equalized, warning_kind, warning)
    finally:
        for leftover in folder.glob(base.name + ".*"):
            if leftover.is_file():
                try:
                    leftover.unlink()
                except OSError:
                    logger.warning("Could not remove a temporary download file.")
