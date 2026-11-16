from mp3_playlist_downloader.settings import Settings
from mp3_playlist_downloader.ui.settings_tabs import GeneralTab, ToolsTab, YouTubeTab


def test_settings_tabs_populate_and_hide_cookie_path(qtbot, tmp_path):
    config = Settings(output_root=str(tmp_path / "music"), cookies_mode="file", cookies_file=str(tmp_path / "private" / "cookies.txt"), auto_equalize=True, theme="dark")
    general, youtube, tools = GeneralTab(config), YouTubeTab(config), ToolsTab(config)
    for tab in (general, youtube, tools):
        qtbot.addWidget(tab)
    assert general.auto_equalize.isChecked()
    assert "irreversible" in general.auto_equalize.text()
    assert general.theme.currentData() == "dark"
    assert youtube.cookie_label.text() == "cookies.txt" and "private" not in youtube.cookie_label.text()
    assert youtube.mode.currentData() == "file"
    assert not tools.mp3gain.text()


def test_settings_roundtrip_and_cancel(qtbot, monkeypatch, tmp_path):
    from mp3_playlist_downloader.settings import load
    from mp3_playlist_downloader.ui.settings_dialog import SettingsDialog

    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    original = Settings(output_root=str(tmp_path / "music"))
    dialog = SettingsDialog(original)
    qtbot.addWidget(dialog)
    dialog.general.auto_equalize.setChecked(True)
    dialog.general.theme.setCurrentIndex(dialog.general.theme.findData("dark"))
    dialog.general.cooldown.setValue(30)
    dialog.save_settings()
    assert dialog.result_settings.auto_equalize and dialog.result_settings.theme == "dark"
    assert load().settings.rate_limit_cooldown_minutes == 30
    assert original.auto_equalize is False
    cancelled = SettingsDialog(dialog.result_settings)
    qtbot.addWidget(cancelled)
    cancelled.general.auto_equalize.setChecked(False)
    cancelled.reject()
    assert load().settings.auto_equalize is True


def test_invalid_cookie_and_tool_paths_are_inline_and_redacted(qtbot, monkeypatch, tmp_path):
    from mp3_playlist_downloader.ui.settings_dialog import SettingsDialog

    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    dialog = SettingsDialog(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(dialog)
    dialog.youtube.mode.setCurrentIndex(dialog.youtube.mode.findData("file"))
    dialog.youtube.set_cookie_file(str(tmp_path / "secret" / "cookies.txt"))
    dialog.save_settings()
    assert "Cookie file" in dialog.error.text()
    assert "secret" not in dialog.error.text() and dialog.result_settings is None
    dialog.youtube.mode.setCurrentIndex(dialog.youtube.mode.findData("none"))
    dialog.tools.mp3gain.setText(str(tmp_path / "missing.exe"))
    dialog.save_settings()
    assert "mp3gain path" in dialog.error.text()
    assert not (tmp_path / "data" / "settings.json").exists()


def test_cookie_test_is_explicit_and_worker_is_offline_fake(qtbot, monkeypatch, tmp_path):
    from mp3_playlist_downloader.models import PlaylistMetadata
    from mp3_playlist_downloader.ui import settings_workers
    from mp3_playlist_downloader.ui.settings_dialog import SettingsDialog

    calls = []
    monkeypatch.setattr(settings_workers, "fetch_playlist", lambda url, settings: calls.append(url) or PlaylistMetadata("Playlist", ()))
    dialog = SettingsDialog(Settings(output_root=str(tmp_path)), test_url="https://www.youtube.com/playlist?list=PL123")
    qtbot.addWidget(dialog)
    assert not calls
    dialog.test_cookies()
    qtbot.waitUntil(lambda: dialog.cookie_worker is None, timeout=5000)
    assert calls == ["https://www.youtube.com/playlist?list=PL123"]
    assert "succeeded" in dialog.youtube.test_result.text()


def test_gain_help_test_missing_binary(qtbot, monkeypatch, tmp_path):
    from mp3_playlist_downloader import equalizer
    from mp3_playlist_downloader.ui.settings_dialog import SettingsDialog

    monkeypatch.setattr(equalizer, "discover", lambda settings: None)
    dialog = SettingsDialog(Settings(output_root=str(tmp_path)))
    qtbot.addWidget(dialog)
    dialog.test_gain()
    qtbot.waitUntil(lambda: dialog.gain_worker is None, timeout=5000)
    assert "mp3gain not found" in dialog.tools.test_result.text()


def test_gain_help_worker_invokes_help_and_redacts(qtbot, monkeypatch, tmp_path):
    import subprocess
    from mp3_playlist_downloader import equalizer
    from mp3_playlist_downloader.ui import settings_workers
    from mp3_playlist_downloader.ui.settings_dialog import SettingsDialog

    monkeypatch.setattr(equalizer, "discover", lambda settings: "fake-mp3gain.exe")
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "mp3gain help\ntoken=secret-value", "")
    monkeypatch.setattr(settings_workers.subprocess, "run", run)
    dialog = SettingsDialog(Settings(output_root=str(tmp_path)))
    qtbot.addWidget(dialog)
    dialog.test_gain()
    qtbot.waitUntil(lambda: dialog.gain_worker is None, timeout=5000)
    assert calls[0][0] == ["fake-mp3gain.exe", "/?"]
    assert calls[0][1]["timeout"] == 10 and calls[0][1]["errors"] == "replace"
    assert "mp3gain help" in dialog.tools.test_result.text()
    assert "secret-value" not in dialog.tools.test_result.text()


def test_cookie_settings_never_store_or_log_cookie_contents(qtbot, monkeypatch, tmp_path, caplog):
    from mp3_playlist_downloader.ui.settings_dialog import SettingsDialog

    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("sensitive-cookie-content", encoding="utf8")
    dialog = SettingsDialog(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(dialog)
    dialog.youtube.mode.setCurrentIndex(dialog.youtube.mode.findData("file"))
    dialog.youtube.set_cookie_file(str(cookie))
    dialog.save_settings()
    saved = (tmp_path / "data" / "settings.json").read_text(encoding="utf8")
    assert dialog.result_settings.cookies_file == str(cookie)
    assert "sensitive-cookie-content" not in saved + caplog.text
    assert dialog.youtube.cookie_label.text() == "cookies.txt"
