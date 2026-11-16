from mp3_playlist_downloader import paths


def test_data_paths_override_and_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "custom"))
    assert paths.db_path() == tmp_path / "custom" / "app.db"
    assert paths.settings_path().name == "settings.json"
    assert paths.log_dir().name == "logs"
    monkeypatch.delenv("MP3PD_DATA_DIR")
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    assert paths.data_dir() == tmp_path / "appdata" / paths.APP_NAME
    monkeypatch.delenv("APPDATA")
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert paths.data_dir() == tmp_path / ".mp3_playlist_downloader"
    assert paths.default_output_root() == tmp_path / "Music" / paths.APP_NAME


def test_playlist_folder_uses_db_paths_not_disk(tmp_path):
    (tmp_path / "Mix").mkdir()
    assert paths.playlist_folder(tmp_path, "Mix") == tmp_path / "Mix"
    assert paths.playlist_folder(tmp_path, "Mix", [tmp_path / "mix", tmp_path / "MIX (2)"]) == tmp_path / "Mix (3)"


def test_tool_path_precedence(monkeypatch, tmp_path):
    configured = tmp_path / "configured.exe"
    configured.write_bytes(b"test")
    monkeypatch.setattr(paths.shutil, "which", lambda name: None)
    assert paths.find_tool("ffmpeg", str(configured)) == str(configured)
    assert paths.find_tool("not-real", str(tmp_path / "missing")) is None


def test_ffprobe_discovered_in_bundled_ffmpeg_directory(monkeypatch, tmp_path):
    import os
    module = tmp_path / "src" / "mp3_playlist_downloader" / "paths.py"
    module.parent.mkdir(parents=True)
    module.touch()
    bundled = tmp_path / "tools" / "ffmpeg" / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"stub")
    monkeypatch.setattr(paths, "__file__", str(module))
    monkeypatch.setattr(paths.shutil, "which", lambda *_: None)
    assert paths.find_tool("ffprobe") == str(bundled)
