"""Validated, atomically persisted per-user settings."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .paths import default_output_root, settings_path

logger = logging.getLogger(__name__)
BROWSERS = {"chrome", "firefox", "edge", "brave", "chromium", "opera", "vivaldi"}


@dataclass
class Settings:
    version: int = 1
    output_root: str = field(default_factory=lambda: str(default_output_root()))
    cookies_mode: str = "none"
    cookies_file: str = ""
    cookies_browser: str = "chrome"
    overwrite_existing: bool = False
    auto_equalize: bool = False
    mp3gain_path: str = ""
    ffmpeg_path: str = ""
    theme: str = "system"
    rate_limit_cooldown_minutes: int = 60
    auto_resume_after_rate_limit: bool = True
    confirm_delete: bool = True
    window_geometry: str = ""


@dataclass
class SettingsResult:
    settings: Settings
    warnings: list[str] = field(default_factory=list)


class SettingsError(ValueError):
    """A safe-to-display validation message, without secret paths."""


def validate(settings: Settings) -> None:
    """Validate settings and verify the output directory can be written."""
    if type(settings.version) is not int or settings.version != 1:
        raise SettingsError("Unsupported settings version.")
    for name in ("overwrite_existing", "auto_equalize", "auto_resume_after_rate_limit", "confirm_delete"):
        if type(getattr(settings, name)) is not bool:
            raise SettingsError(f"{name} must be a boolean.")
    for name in ("output_root", "cookies_mode", "cookies_file", "cookies_browser", "mp3gain_path", "ffmpeg_path", "theme", "window_geometry"):
        if not isinstance(getattr(settings, name), str):
            raise SettingsError(f"{name} must be text.")
    if settings.cookies_mode not in {"none", "file", "browser"}:
        raise SettingsError("Invalid cookies mode.")
    if settings.cookies_browser not in BROWSERS:
        raise SettingsError("Invalid cookies browser.")
    if settings.cookies_mode == "file":
        try:
            with open(settings.cookies_file, "rb"):
                pass
        except (OSError, ValueError):
            raise SettingsError("Cookie file is missing or unreadable.") from None
    if settings.theme not in {"system", "light", "dark"}:
        raise SettingsError("Invalid theme.")
    for name, label in (("ffmpeg_path", "ffmpeg"), ("mp3gain_path", "mp3gain")):
        tool_path = getattr(settings, name)
        if tool_path:
            try:
                if not Path(tool_path).is_file():
                    raise OSError("not a file")
                with open(tool_path, "rb"):
                    pass
            except (OSError, ValueError):
                raise SettingsError(f"{label} path is missing or unreadable.") from None
    cooldown = settings.rate_limit_cooldown_minutes
    if type(cooldown) is not int or not 5 <= cooldown <= 1440:
        raise SettingsError("Cooldown must be between 5 and 1440 minutes.")
    if not settings.output_root.strip():
        raise SettingsError("Output root is required.")
    try:
        root = Path(settings.output_root)
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=root):
            pass
    except (OSError, ValueError):
        raise SettingsError("Output folder cannot be created or written.") from None


def load(path: Path | None = None) -> SettingsResult:
    """Load safely; invalid or unreadable settings fall back to defaults."""
    path = path or settings_path()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or set(data) - {f.name for f in fields(Settings)}:
                raise SettingsError("Invalid settings fields.")
            settings = Settings(**data)
        else:
            settings = Settings()
        validate(settings)
        return SettingsResult(settings)
    except (OSError, ValueError, TypeError) as exc:
        # Only controlled validation messages are safe; JSON and OS errors may reveal paths.
        reason = str(exc) if isinstance(exc, SettingsError) else "Settings could not be read."
        logger.warning("Invalid settings; using defaults: %s", reason)
        default = Settings()
        warnings = [f"Invalid settings; using defaults. {reason}"]
        try:
            validate(default)
        except SettingsError as error:
            warnings.append(str(error))
        return SettingsResult(default, warnings)


def save(settings: Settings, path: Path | None = None) -> None:
    """Validate and replace the settings file atomically in the same directory."""
    validate(settings)
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".settings-", suffix=".tmp", delete=False) as temp:
            temp_name = temp.name
            json.dump(asdict(settings), temp, indent=2, ensure_ascii=False)
            temp.write("\n")
            temp.flush()
            os.fsync(temp.fileno())
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)
