"""Application paths and Windows-safe playlist folder names."""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path
from typing import Iterable

APP_NAME = "MP3 Playlist Downloader"
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)


def data_dir() -> Path:
    """Return the overridden or per-user application data directory."""
    if os.environ.get("MP3PD_DATA_DIR"):
        return Path(os.environ["MP3PD_DATA_DIR"])
    if os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / APP_NAME
    return Path(os.environ.get("USERPROFILE") or Path.home()) / ".mp3_playlist_downloader"


def db_path() -> Path:
    return data_dir() / "app.db"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def log_dir() -> Path:
    return data_dir() / "logs"


def default_output_root() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "Music" / APP_NAME


def find_tool(name: str, configured: str = "") -> str | None:
    """Find an executable from settings, bundled tools, or PATH, in that order."""
    root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
    exe = f"{name}.exe" if os.name == "nt" else name
    bundle = "ffmpeg" if name == "ffprobe" else name
    candidates = [configured, str(root / "tools" / bundle / exe), shutil.which(exe) or ""]
    return next((item for item in candidates if item and Path(item).is_file()), None)


def sanitize_filename(value: str) -> str:
    """Make a Windows-safe, bounded filename component without losing Unicode."""
    name = _INVALID.sub("_", value).strip().rstrip(". ")[:120].rstrip(". ")
    if not name:
        return "Untitled"
    if _RESERVED.match(name):
        name = "_" + name[:119]
    return name


def playlist_folder(root: Path, title: str, used_paths: Iterable[str | Path] = ()) -> Path:
    """Allocate by DB ownership, not disk existence; never change existing folders."""
    used = {os.path.abspath(str(path)).casefold() for path in used_paths}
    name = sanitize_filename(title)
    candidate = Path(root) / name
    number = 2
    while os.path.abspath(str(candidate)).casefold() in used:
        suffix = f" ({number})"
        candidate = Path(root) / (name[:120 - len(suffix)].rstrip(". ") + suffix)
        number += 1
    return candidate
