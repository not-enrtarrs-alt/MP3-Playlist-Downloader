"""Common offline test configuration."""

import os
import shutil
import subprocess

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def silent_mp3(tmp_path_factory):
    """Generate offline silence once, or skip clearly when ffmpeg is unavailable."""
    executable = shutil.which("ffmpeg")
    if not executable:
        pytest.skip("ffmpeg is required to generate the silent MP3 fixture")
    path = tmp_path_factory.mktemp("audio") / "silent.mp3"
    result = subprocess.run([executable, "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "0.3", "-q:a", "9", "-acodec", "libmp3lame", str(path)], capture_output=True, timeout=30)
    if result.returncode != 0 or not path.is_file():
        pytest.skip("ffmpeg cannot generate the silent MP3 fixture")
    return path
