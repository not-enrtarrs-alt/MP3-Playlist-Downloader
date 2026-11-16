"""Synchronous yt-dlp Python API wrapper for flat playlist fetching."""

from __future__ import annotations

from typing import Any, Callable

import yt_dlp

from ..models import PlaylistMetadata
from ..settings import Settings
from .errors import YouTubeError, classify_error
from .parse import normalize_playlist_url, parse_flat_playlist


class _PrivateYtDlpLogger:
    """Discard upstream diagnostic text, which may contain credentials or paths."""

    def debug(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        pass

    def error(self, message: str) -> None:
        pass


def cookie_options(settings: Settings) -> dict[str, Any]:
    """Build yt-dlp auth options without reading or logging cookie contents."""
    if settings.cookies_mode == "file":
        return {"cookiefile": settings.cookies_file}
    if settings.cookies_mode == "browser":
        return {"cookiesfrombrowser": (settings.cookies_browser,)}
    return {}


def fetch_playlist(url: str, settings: Settings, *, downloader_factory: Callable[..., Any] | None = None) -> PlaylistMetadata:
    """Fetch and parse once. Call from a worker, never from the GUI thread."""
    url = normalize_playlist_url(url)
    options = {"extract_flat": "in_playlist", "skip_download": True, "quiet": True, "no_warnings": True, "logger": _PrivateYtDlpLogger(), **cookie_options(settings)}
    try:
        factory = downloader_factory or yt_dlp.YoutubeDL
        with factory(options) as downloader:
            info = downloader.extract_info(url, download=False)
            if not isinstance(info, dict):
                raise YouTubeError("YouTube did not return playlist information.")
            return parse_flat_playlist(info)
    except YouTubeError:
        raise
    except Exception as error:
        raise classify_error(error) from None
