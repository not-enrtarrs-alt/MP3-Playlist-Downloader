"""Minimal ID3v2.3 tags and safe thumbnail conversion."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import requests
from mutagen.easyid3 import EasyID3
from mutagen.id3 import APIC, ID3, ID3NoHeaderError, TIT2

from .youtube.parse import title_and_artist

logger = logging.getLogger(__name__)


def tag_file(path: Path, raw_title: str, uploader: str | None, album: str, cover: bytes | None = None,
             custom_title: str | None = None) -> None:
    """Replace tags with title, artist, album and optional JPEG cover only."""
    try:
        tags = ID3(path)
        tags.clear()
    except ID3NoHeaderError:
        tags = ID3()
    tags.save(path, v2_version=3)
    easy = EasyID3(path)
    title, artist = title_and_artist(raw_title, uploader, custom_title)
    easy["title"] = title
    easy["artist"] = artist
    easy["album"] = album
    easy.save(path, v2_version=3)
    tags = ID3(path)
    tags.delall("APIC")
    if cover:
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))
    tags.save(path, v2_version=3)


def retag_album(path: Path, album: str) -> None:
    """Update album only, preserving all other frames."""
    try:
        easy = EasyID3(path)
    except ID3NoHeaderError:
        ID3().save(path, v2_version=3)
        easy = EasyID3(path)
    easy["album"] = album
    easy.save(path, v2_version=3)


def retag_title(path: Path, title: str) -> None:
    """Update only TIT2 while retaining all other ID3 frames."""
    if not path.is_file():
        raise FileNotFoundError("MP3 file is missing.")
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.delall("TIT2")
    tags.add(TIT2(encoding=3, text=[title]))
    tags.save(path, v2_version=3)


def _as_jpeg(content: bytes, ffmpeg: str | None) -> bytes | None:
    if content.startswith(b"\xff\xd8\xff"):
        return content
    if not ffmpeg or not content:
        return None
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        suffix = ".png"
    elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        suffix = ".webp"
    elif content.startswith((b"GIF87a", b"GIF89a")):
        suffix = ".gif"
    else:
        suffix = ".input"
    try:
        with tempfile.TemporaryDirectory(prefix="mp3pd-cover-") as temp:
            source, output = Path(temp) / ("cover" + suffix), Path(temp) / "cover.jpg"
            source.write_bytes(content)
            run = subprocess.run([ffmpeg, "-y", "-i", str(source), "-frames:v", "1", str(output)], capture_output=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if run.returncode == 0 and output.is_file():
                result = output.read_bytes()
                return result if result.startswith(b"\xff\xd8\xff") else None
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def load_cover(video_id: str, thumbnail: Path | None = None, ffmpeg: str | None = None,
               *, http_get: Callable | None = None) -> bytes | None:
    """Prefer a local thumbnail, then try maxres and hq; return JPEG or None."""
    http_get = http_get or requests.get
    if thumbnail:
        try:
            content = _as_jpeg(thumbnail.read_bytes(), ffmpeg)
            if content:
                return content
        except OSError:
            pass
    for quality in ("maxresdefault", "hqdefault"):
        try:
            response = http_get(f"https://i.ytimg.com/vi/{video_id}/{quality}.jpg", timeout=10)
            response.raise_for_status()
            content = _as_jpeg(response.content, ffmpeg)
            if content:
                return content
        except (requests.RequestException, OSError):
            continue
    logger.warning("Thumbnail unavailable; proceeding without cover art.")
    return None
