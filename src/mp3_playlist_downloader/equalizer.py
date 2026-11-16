"""Safe, synchronous mp3gain discovery and permanent track-gain execution."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .logging_setup import redact
from .paths import find_tool
from .settings import Settings

logger = logging.getLogger(__name__)

# These are the requested Windows mp3gain flags. They must be verified against
# the installed binary's /? output; none was available in this environment.
MP3GAIN_FLAGS = ("/r", "/k", "/s", "s")
MISSING_MESSAGE = "mp3gain not found. Set its path in Settings → Tools or install it."


class EqualizerError(Exception):
    """An equalization error safe to show without subprocess output or paths."""


class EqualizerMissing(EqualizerError):
    pass


@dataclass
class EqualizeSummary:
    succeeded: int = 0
    failed: int = 0
    cancelled: bool = False
    total: int = 0


def discover(settings: Settings) -> str | None:
    """Find configured, bundled, or PATH mp3gain in that order."""
    return find_tool("mp3gain", settings.mp3gain_path)


def apply(path: Path, settings: Settings) -> None:
    """Permanently apply track gain, raising on missing binary or any failure."""
    executable = discover(settings)
    if not executable:
        raise EqualizerMissing(MISSING_MESSAGE)
    if not Path(path).is_file():
        raise EqualizerError("The MP3 file is missing or inaccessible.")
    try:
        result = subprocess.run([executable, *MP3GAIN_FLAGS, str(path)], capture_output=True,
                                text=True, errors="replace", timeout=180,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        logger.warning("mp3gain timed out after 180 seconds")
        raise EqualizerError("mp3gain timed out after 180 seconds.") from None
    except OSError:
        logger.warning("mp3gain could not be started")
        raise EqualizerError("mp3gain could not be started.") from None
    if result.returncode != 0:
        output = redact((result.stdout or "") + (result.stderr or ""))[:500]
        logger.warning("mp3gain failed (exit %s): %s", result.returncode, output)
        raise EqualizerError(f"mp3gain failed (exit code {result.returncode}).")
    logger.info("mp3gain completed successfully")
