"""Offline checks for packaging scripts; never invoke the actual installer."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name != "nt", reason="PowerShell launcher targets Windows")
def test_dev_launcher_reports_version():
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts" / "dev_run.ps1"), "version"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and result.stdout.strip() == "0.1.0"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell launcher targets Windows")
def test_dev_launcher_explains_missing_venv(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(ROOT / "scripts" / "dev_run.ps1", scripts / "dev_run.ps1")
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(scripts / "dev_run.ps1"), "version"], capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and "virtual environment not found" in result.stderr.lower()


def test_installer_is_per_user_and_preserves_app_data():
    script = (ROOT / "scripts" / "installer.iss").read_text(encoding="utf8").lower()
    assert "privilegesrequired=lowest" in script
    assert "defaultdirname={localappdata}\\programs\\" in script
    assert "[uninstalldelete]" not in script and "{userappdata}" not in script
    assert "myappversion" in script and "recursesubdirs" in script


def test_build_does_not_allow_silent_overwrite_and_version_matches():
    import tomllib
    from mp3_playlist_downloader import __version__
    build = (ROOT / "scripts" / "build.ps1").read_text(encoding="utf8")
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf8"))
    assert "--noconfirm" not in build
    assert '"/F$installerName"' in build and "[Guid]::NewGuid()" in build
    assert metadata["project"]["version"] == __version__


def test_pyinstaller_launcher_imports_package():
    import sys
    from mp3_playlist_downloader import __version__
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "launcher.py"), "version"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and result.stdout.strip() == __version__


def test_dependency_probe_accepts_only_this_editable_project(tmp_path):
    import sys
    script = ROOT / "scripts" / "dependency_probe.py"
    valid = subprocess.run([sys.executable, str(script), str(ROOT)], capture_output=True, text=True, timeout=30)
    unrelated = subprocess.run([sys.executable, str(script), str(tmp_path)], capture_output=True, text=True, timeout=30)
    assert valid.returncode == 0 and unrelated.returncode == 1


@pytest.mark.skipif(os.name != "nt", reason="PowerShell build targets Windows")
def test_build_refuses_existing_output_without_overwriting(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(ROOT / "scripts" / "build.ps1", scripts / "build.ps1")
    destination = tmp_path / "dist" / "MP3 Playlist Downloader"
    destination.mkdir(parents=True)
    marker = destination / "user-file.txt"
    marker.write_text("preserve", encoding="utf8")
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(scripts / "build.ps1")], capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and "already exists" in result.stderr
    assert marker.read_text(encoding="utf8") == "preserve"
