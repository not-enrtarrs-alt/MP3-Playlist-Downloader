"""Safe YouTube error types and classification without exposing credentials."""

from __future__ import annotations

import re


class YouTubeError(Exception):
    """Safe-to-display failure; raw yt-dlp errors can contain private paths."""


class RateLimitedError(YouTubeError):
    pass


class UnavailableError(YouTubeError):
    pass


class NetworkError(YouTubeError):
    pass


class AudioConversionError(YouTubeError):
    """An ffmpeg/ffprobe processing failure with no sensitive details."""


def classify_error(error: BaseException) -> YouTubeError:
    """Classify the raw exception but never return its potentially sensitive text."""
    text = str(error).casefold()
    if any(term in text for term in ("429", "too many requests", "confirm you're not a bot", "confirm you’re not a bot", "try again later")):
        return RateLimitedError("YouTube is rate-limiting requests. Try again later or configure cookies.")
    if any(term in text for term in ("private video", "deleted video", "members-only", "members only", "video unavailable", "this content isn't available", "this content is not available")):
        return UnavailableError("The video or playlist is unavailable or private.")
    if isinstance(error, (TimeoutError, ConnectionError)) or any(term in text for term in ("timed out", "timeout", "connection reset", "connection refused", "dns", "name resolution", "network is unreachable")) or re.search(r"\b(?:http error\s*)?5\d\d\b", text):
        return NetworkError("A network error occurred. Check your connection and retry.")
    if any(term in text for term in ("postprocessing", "post-processing", "ffmpeg", "ffprobe", "audio conversion", "file audio codec")):
        return AudioConversionError("Audio conversion failed. Check ffmpeg and ffprobe in Settings → Tools.")
    return YouTubeError("YouTube could not read this playlist. Check the URL and cookie settings.")
