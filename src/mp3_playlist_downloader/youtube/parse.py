"""Pure URL, flat playlist, and topic metadata parsing."""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ..models import PlaylistMetadata, VideoMetadata

logger = logging.getLogger(__name__)
_PLAYLIST_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_TOPIC = re.compile(r"\s+-\s+topic$", re.IGNORECASE)
_OFFICIAL = re.compile(r"(?<!\w)(?:official|officiel(?:le)?)(?!\w)", re.IGNORECASE)
_FEATURE = re.compile(r"(?<!\w)(?:feat(?:uring)?|ft)\.?(?=\s|@|[\[(]|$)", re.IGNORECASE)
_OFFICIAL_TAIL = re.compile(r"\s*(?:[-–—|]\s*)?\bofficial\s+(?:(?:music|lyric|lyrics|concept|english|visual|animated|\d+k)\s+)*(?:audio|video|visuali[sz]er|version)\s*$", re.IGNORECASE)
_FRENCH_TAIL = re.compile(r"\s*(?:[-–—|]\s*)?(?:audio|clip|vid[eé]o)\s+officiel(?:le)?\s*$", re.IGNORECASE)
_ALBUM_TAIL = re.compile(r"\s+(?:special|deluxe|expanded|anniversary)\s+edition(?:\s+album)?\s*$", re.IGNORECASE)
_VERSION_LABEL = re.compile(r"^(?:(?:radio|extended|acoustic|instrumental|karaoke|english)\s+(?:edit|version|mix)|live(?:\s+(?:at|from|in|on)\b.*)?|hd|4k)$", re.IGNORECASE)


def normalize_playlist_url(url: str) -> str:
    """Canonicalize a trusted YouTube playlist URL or raise a safe error."""
    value = url.strip()
    if "://" not in value:
        value = "https://" + value
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        if parsed.scheme.lower() not in {"http", "https"} or host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"} or parsed.username or parsed.password or parsed.port not in (None, 80, 443):
            raise ValueError("Enter a valid YouTube playlist URL.")
        ids = parse_qs(parsed.query).get("list", [])
    except ValueError:
        raise ValueError("Enter a valid YouTube playlist URL.") from None
    if not ids:
        raise ValueError("This is a single video. Add a playlist URL instead.")
    playlist_id = ids[0]
    if not _PLAYLIST_ID.fullmatch(playlist_id):
        raise ValueError("Enter a valid YouTube playlist URL.")
    if playlist_id.upper().startswith("RD"):
        raise ValueError("This is an endless mix, not a playlist.")
    return f"https://www.youtube.com/playlist?list={playlist_id}"


def is_topic(uploader: str | None) -> bool:
    return bool(uploader and _TOPIC.search(uploader))


def _normalized_artist(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKC", value).casefold() if char.isalnum())


def _balanced_brackets(value: str) -> bool:
    """Avoid stripping when malformed brackets make title boundaries unclear."""
    stack: list[str] = []
    pairs = {")": "(", "]": "["}
    for char in value:
        if char in "([":
            stack.append(char)
        elif char in ")]":
            if not stack or stack.pop() != pairs[char]:
                return False
    return not stack


def _split_artist_prefix(value: str) -> tuple[str, str] | None:
    """Find a spaced artist separator only outside bracketed title metadata."""
    stack: list[str] = []
    pairs = {")": "(", "]": "["}
    for index, char in enumerate(value):
        if char in "([":
            stack.append(char)
        elif char in ")]" and stack and stack[-1] == pairs[char]:
            stack.pop()
        elif not stack and char in "-–—:" and 0 < index < len(value) - 1:
            if not (value[index - 1].isspace() or value[index + 1].isspace()):
                continue
            before, after = value[:index].strip(), value[index + 1:].strip()
            if before and after:
                # A suffix such as "Song - Official Audio" is not an artist prefix.
                if (_OFFICIAL_TAIL.fullmatch(after) or _FRENCH_TAIL.fullmatch(after)):
                    return None
                return before, after
    return None


def _strip_bracketed_metadata(value: str) -> str:
    """Remove recognizable metadata groups while keeping unknown title text."""
    stack: list[tuple[str, int]] = []
    spans: list[tuple[int, int]] = []
    pairs = {")": "(", "]": "["}
    for index, char in enumerate(value):
        if char in "([":
            stack.append((char, index))
        elif char in ")]" and stack and stack[-1][0] == pairs[char]:
            _, start = stack.pop()
            if not stack:
                content = value[start + 1:index].strip()
                lower = content.casefold()
                feature = _FEATURE.match(content)
                if (_OFFICIAL.search(content) or feature or re.search(r"\b(?:album|remix|remaster(?:ed)?)\b", lower)
                        or lower.startswith("from ") or _VERSION_LABEL.fullmatch(content)
                        or re.fullmatch(r"(?:lyrics?|audio|lyric(?:s)? video|music video)", lower)):
                    spans.append((start, index + 1))
    for start, end in reversed(spans):
        value = value[:start] + value[end:]
    return value


def _official_title(title: str, uploader: str | None) -> str:
    """Conservatively clean official titles without guessing mismatched artists."""
    original = title
    if not _balanced_brackets(title):
        return original
    title = title.strip()
    prefix = _split_artist_prefix(title)
    if prefix:
        credited = _FEATURE.split(prefix[0], maxsplit=1)[0].strip(" ,&")
        uploader_artist = _TOPIC.sub("", uploader or "").strip()
        if not uploader_artist or not _normalized_artist(credited) or _normalized_artist(credited) != _normalized_artist(uploader_artist):
            return original
        title = prefix[1]
    title = _strip_bracketed_metadata(title)
    feature = _FEATURE.search(title)
    if feature:
        title = title[:feature.start()]
    title = _OFFICIAL_TAIL.sub("", title)
    title = _FRENCH_TAIL.sub("", title)
    title = _ALBUM_TAIL.sub("", title)
    title = re.sub(r"\s{2,}", " ", title).strip(" \t-–—|")
    return title if title else original


def title_and_artist(title: str, uploader: str | None, custom_title: str | None = None) -> tuple[str, str]:
    """Return the display/tag title and artist without changing the raw DB title."""
    if custom_title:
        _, artist = title_and_artist(title, uploader)
        return custom_title, artist
    if _OFFICIAL.search(title):
        artist = _TOPIC.sub("", uploader or "").strip() or "Unknown Artist"
        return _official_title(title, uploader), artist
    if not is_topic(uploader):
        return title, uploader or "Unknown Artist"
    artist = _TOPIC.sub("", uploader or "").strip() or "Unknown Artist"
    match = re.match(r"^(.+?)\s+-\s+(.+)$", title)
    if match and _normalized_artist(match.group(1)) == _normalized_artist(artist):
        return match.group(2), match.group(1)
    return title, artist


def _thumbnail(entry: dict[str, Any], video_id: str) -> str:
    candidates = [item for item in entry.get("thumbnails") or [] if isinstance(item, dict) and isinstance(item.get("url"), str) and item["url"]]
    if candidates:
        def size(item: dict[str, Any]) -> float:
            width, height = item.get("width"), item.get("height")
            return float(width) * float(height) if isinstance(width, (int, float)) and isinstance(height, (int, float)) else 0
        return max(candidates, key=size)["url"]
    thumbnail = entry.get("thumbnail")
    return thumbnail if isinstance(thumbnail, str) and thumbnail else f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def parse_flat_playlist(info: dict[str, Any]) -> PlaylistMetadata:
    """Parse flat entries, preserving original positions and the first duplicate."""
    title = info.get("title")
    title = title.strip() if isinstance(title, str) and title.strip() else "Playlist"
    videos: list[VideoMetadata] = []
    seen: set[str] = set()
    for position, entry in enumerate(info.get("entries") or []):
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"].strip():
            continue
        video_id = entry["id"].strip()
        if video_id in seen:
            logger.info("Skipping duplicate video ID %s", video_id)
            continue
        seen.add(video_id)
        raw_title = entry.get("title")
        unavailable = not isinstance(raw_title, str) or not raw_title.strip() or raw_title.strip().casefold() in {"[private video]", "[deleted video]", "[unavailable video]"}
        raw_title = raw_title if isinstance(raw_title, str) and raw_title.strip() else "[Unavailable video]"
        uploader = entry.get("uploader")
        uploader = uploader if isinstance(uploader, str) and uploader else None
        duration = entry.get("duration")
        duration = int(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(duration) and duration >= 0 else None
        videos.append(VideoMetadata(video_id, raw_title, uploader, duration, _thumbnail(entry, video_id), position, unavailable, is_topic(uploader)))
    return PlaylistMetadata(title, tuple(videos))
