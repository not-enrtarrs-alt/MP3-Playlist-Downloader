import json

import pytest

from mp3_playlist_downloader.settings import Settings, SettingsError, load, save, validate


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))


def test_defaults_and_round_trip(tmp_path):
    result = load()
    assert result.warnings == []
    assert result.settings.auto_equalize is False
    assert result.settings.overwrite_existing is False
    assert (tmp_path / "Music" / "MP3 Playlist Downloader").is_dir()
    result.settings.theme = "dark"
    save(result.settings)
    assert load().settings == result.settings
    assert json.loads((tmp_path / "data" / "settings.json").read_text())['theme'] == 'dark'
    assert not list((tmp_path / "data").glob(".settings-*.tmp"))


@pytest.mark.parametrize("changes", [
    {"cookies_mode": "other"}, {"cookies_mode": "file", "cookies_file": "missing-secret"},
    {"cookies_browser": "bad"}, {"theme": "bad"}, {"rate_limit_cooldown_minutes": 4},
    {"rate_limit_cooldown_minutes": 1441}, {"rate_limit_cooldown_minutes": True},
    {"auto_equalize": 1}, {"output_root": ""}, {"version": 2},
])
def test_validation_rejects_invalid_values(changes):
    with pytest.raises(SettingsError):
        validate(Settings(**changes))


def test_cookie_path_not_in_warnings(tmp_path, caplog):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"cookies_mode": "file", "cookies_file": "secret-path"}))
    result = load(path)
    assert result.warnings
    assert "secret-path" not in str(result.warnings) + caplog.text


def test_invalid_json_falls_back(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{bad", encoding="utf8")
    result = load(path)
    assert result.warnings and result.settings.theme == "system"


def test_failed_atomic_replace_keeps_existing_file(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text("old", encoding="utf8")
    def fail(*args):
        raise OSError("replace failed")
    monkeypatch.setattr("mp3_playlist_downloader.settings.os.replace", fail)
    with pytest.raises(OSError):
        save(Settings(), path)
    assert path.read_text() == "old"
    assert not list(tmp_path.glob(".settings-*.tmp"))


def test_explicit_tool_paths_must_exist(tmp_path):
    with pytest.raises(SettingsError, match="ffmpeg path"):
        validate(Settings(ffmpeg_path=str(tmp_path / "missing.exe")))
    with pytest.raises(SettingsError, match="mp3gain path"):
        validate(Settings(mp3gain_path=str(tmp_path / "missing.exe")))
    executable = tmp_path / "tool.exe"
    executable.write_bytes(b"stub")
    validate(Settings(ffmpeg_path=str(executable), mp3gain_path=str(executable)))
