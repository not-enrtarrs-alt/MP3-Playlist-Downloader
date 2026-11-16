"""Check whether the local editable project and build dependencies are installed."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

MODULES = ("mp3_playlist_downloader", "PySide6.QtWidgets", "yt_dlp", "mutagen", "send2trash", "requests", "pytest", "pytestqt", "pytest_mock", "PyInstaller")


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    try:
        modules = [importlib.import_module(name) for name in MODULES]
        package = Path(modules[0].__file__).resolve()
        if not package.is_relative_to(root / "src"):
            return 1
    except (ImportError, OSError, TypeError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
