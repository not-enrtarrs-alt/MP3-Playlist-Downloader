"""Exercise the actual CLI and GUI bootstrap without a network or real user data."""

import os
import subprocess
import sys


def test_gui_bootstrap_and_exit(tmp_path):
    env = os.environ.copy()
    env.update({"QT_QPA_PLATFORM": "offscreen", "MP3PD_DATA_DIR": str(tmp_path / "data"), "USERPROFILE": str(tmp_path)})
    code = (
        "from PySide6.QtCore import QTimer; "
        "from PySide6.QtWidgets import QApplication; "
        "from mp3_playlist_downloader.app import run; "
        "app=QApplication([]); QTimer.singleShot(500, app.quit); raise SystemExit(run())"
    )
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "data" / "app.db").exists()
    assert (tmp_path / "data" / "logs" / "app.log").exists()


def test_cli_doctor_and_version(tmp_path):
    env = os.environ.copy()
    env.update({"MP3PD_DATA_DIR": str(tmp_path / "data"), "USERPROFILE": str(tmp_path)})
    for command in ("doctor", "version"):
        result = subprocess.run([sys.executable, "-m", "mp3_playlist_downloader", command], env=env, cwd=tmp_path, capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip()
