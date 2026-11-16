"""Offline diagnostics for the desktop application."""

from __future__ import annotations

import importlib.metadata
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import __version__, db, paths, settings
from .redaction import redact


def _tool(name: str, configured: str) -> str | None:
    """Find configured, bundled, then PATH executable without running it."""
    return paths.find_tool(name, configured)


def doctor() -> tuple[dict[str, Any], int]:
    """Inspect configuration and database without any network access."""
    result: dict[str, Any] = {"version": __version__, "errors": [], "warnings": [], "checks": {}}
    checks, errors, warnings = result["checks"], result["errors"], result["warnings"]
    checks["python"] = sys.version.split()[0]
    if sys.version_info < (3, 11):
        errors.append("Python 3.11 or newer is required.")
    for distribution in ("PySide6", "yt-dlp"):
        try:
            checks[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            errors.append(f"{distribution} is not installed.")
    try:
        import PySide6.QtWidgets  # noqa: F401
    except ImportError:
        errors.append("PySide6 could not be imported.")
    try:
        directory = paths.data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=directory):
            pass
        checks["data_writable"] = True
    except OSError:
        checks["data_writable"] = False
        errors.append("Data folder is not writable.")
    loaded = settings.load()
    if loaded.warnings:
        errors.extend(loaded.warnings)
    config = loaded.settings
    checks["settings_valid"] = not bool(loaded.warnings)
    checks["output_writable"] = not any("Output folder" in warning for warning in loaded.warnings)
    checks["cookies"] = config.cookies_mode
    if config.cookies_mode == "none":
        warnings.append("No YouTube cookies configured (optional).")
    sibling_probe = str(Path(config.ffmpeg_path).parent / ("ffprobe.exe" if os.name == "nt" else "ffprobe")) if config.ffmpeg_path else ""
    for name, configured in (("ffmpeg", config.ffmpeg_path), ("ffprobe", sibling_probe), ("mp3gain", config.mp3gain_path)):
        executable = _tool(name, configured)
        checks[name] = executable or "not found"
        if not executable:
            warnings.append(f"{name} not found; {'equalization' if name == 'mp3gain' else 'audio processing'} unavailable.")
        elif name in {"ffmpeg", "ffprobe"}:
            try:
                run = subprocess.run([executable, "-version"], capture_output=True, text=True, errors="replace", timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                lines = (run.stdout or run.stderr or "").splitlines()
                if run.returncode == 0 and lines:
                    checks[name + "_version"] = redact(lines[0])[:500]
                else:
                    warnings.append(f"{name} version could not be checked.")
            except (OSError, subprocess.TimeoutExpired):
                warnings.append(f"{name} version could not be checked.")
        elif name == "mp3gain":
            try:
                run = subprocess.run([executable, "/?"], capture_output=True, text=True, errors="replace", timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                checks["mp3gain_help"] = redact((run.stdout or "") + (run.stderr or ""))[:4000]
            except (OSError, subprocess.TimeoutExpired):
                warnings.append("mp3gain help could not be checked.")
    try:
        connection = db.connect()
        try:
            db.initialize(connection)
            checks["schema_version"] = connection.execute("SELECT value FROM meta WHERE key=?", ("schema_version",)).fetchone()[0]
            checks["queued"] = connection.execute("SELECT COUNT(*) FROM videos WHERE download_state=?", ("queued",)).fetchone()[0]
            checks["missing_downloads"] = sum(1 for row in connection.execute("SELECT file_path FROM videos WHERE downloaded=1") if not row[0] or not Path(row[0]).is_file())
            checks["pending_extras"] = connection.execute("SELECT COUNT(*) FROM extra_files WHERE disposition=?", ("pending",)).fetchone()[0]
        finally:
            connection.close()
    except (sqlite3.Error, OSError, RuntimeError):
        errors.append("Database could not be initialized or has an unsupported schema.")
    return result, 2 if errors else 0


def print_doctor(as_json: bool = False) -> int:
    result, code = doctor()
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print("MP3 Playlist Downloader — doctor")
        for key, value in result["checks"].items():
            print(f"  {key}: {value}")
        for level in ("warnings", "errors"):
            for message in result[level]:
                print(f"  {level[:-1].upper()}: {message}")
    return code
