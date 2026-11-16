import logging
import os
import subprocess
from pathlib import Path

import pytest

from mp3_playlist_downloader import equalizer, paths
from mp3_playlist_downloader.settings import Settings


def test_discovery_order(monkeypatch, tmp_path):
    module = tmp_path / "src" / "mp3_playlist_downloader" / "paths.py"
    module.parent.mkdir(parents=True)
    module.touch()
    bundled = tmp_path / "tools" / "mp3gain" / ("mp3gain.exe" if os.name == "nt" else "mp3gain")
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"bundled")
    configured, on_path = tmp_path / "configured.exe", tmp_path / "path.exe"
    configured.write_bytes(b"configured")
    on_path.write_bytes(b"path")
    monkeypatch.setattr(paths, "__file__", str(module))
    monkeypatch.setattr(paths.shutil, "which", lambda _: str(on_path))
    assert equalizer.discover(Settings(mp3gain_path=str(configured))) == str(configured)
    configured.unlink()
    assert equalizer.discover(Settings(mp3gain_path=str(configured))) == str(bundled)
    bundled.unlink()
    assert equalizer.discover(Settings()) == str(on_path)
    on_path.unlink()
    assert equalizer.discover(Settings()) is None


def test_command_flags_and_success(monkeypatch, tmp_path):
    file = tmp_path / "song.mp3"
    file.write_bytes(b"audio")
    monkeypatch.setattr(equalizer, "discover", lambda settings: "mp3gain.exe")
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "ok", "")
    monkeypatch.setattr(equalizer.subprocess, "run", run)
    equalizer.apply(file, Settings())
    assert calls[0][0] == ["mp3gain.exe", "/r", "/k", "/s", "s", str(file)]
    assert calls[0][1]["timeout"] == 180 and calls[0][1]["errors"] == "replace"
    assert calls[0][1]["capture_output"] and calls[0][1]["text"]


def test_missing_or_invalid_file_does_not_execute(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("subprocess must not run")
    monkeypatch.setattr(equalizer.subprocess, "run", forbidden)
    monkeypatch.setattr(equalizer, "discover", lambda settings: None)
    with pytest.raises(equalizer.EqualizerMissing, match="mp3gain not found"):
        equalizer.apply(tmp_path / "missing.mp3", Settings())
    monkeypatch.setattr(equalizer, "discover", lambda settings: "mp3gain.exe")
    with pytest.raises(equalizer.EqualizerError, match="missing"):
        equalizer.apply(tmp_path / "missing.mp3", Settings())


def test_failure_output_truncated_and_safe(monkeypatch, tmp_path, caplog):
    file = tmp_path / "song.mp3"
    file.write_bytes(b"audio")
    monkeypatch.setattr(equalizer, "discover", lambda settings: "mp3gain.exe")
    monkeypatch.setattr(equalizer.subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "x" * 700 + "SENTINEL", ""))
    with caplog.at_level(logging.WARNING), pytest.raises(equalizer.EqualizerError) as error:
        equalizer.apply(file, Settings())
    assert "SENTINEL" not in caplog.text and "exit code 1" in str(error.value)
    assert "x" * 501 not in caplog.text


def test_timeout_is_failure(monkeypatch, tmp_path):
    file = tmp_path / "song.mp3"
    file.write_bytes(b"audio")
    monkeypatch.setattr(equalizer, "discover", lambda settings: "mp3gain.exe")
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 180)
    monkeypatch.setattr(equalizer.subprocess, "run", timeout)
    with pytest.raises(equalizer.EqualizerError, match="timed out"):
        equalizer.apply(file, Settings())
