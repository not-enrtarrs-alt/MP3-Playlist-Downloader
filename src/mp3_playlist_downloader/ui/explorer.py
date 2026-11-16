"""Open a downloaded file in the system file manager."""

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def reveal_file(path: str) -> None:
    """Select the file in Explorer on Windows, otherwise open its parent."""
    target = Path(path)
    if not target.is_file():
        return
    if os.name == "nt":
        try:
            subprocess.Popen(["explorer.exe", "/select,", str(target)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent)))
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent)))
