import json

from mp3_playlist_downloader import cli


def test_doctor_offline_and_creates_db(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(cli, "_tool", lambda *_: None)
    assert cli.print_doctor(True) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["checks"]["schema_version"] == "2"
    assert data["checks"]["queued"] == 0
    assert any("mp3gain" in warning for warning in data["warnings"])
    assert (tmp_path / "data" / "app.db").is_file()


def test_doctor_invalid_settings_is_error_without_secret(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "settings.json").write_text('{"cookies_mode":"file","cookies_file":"secret-cookie-path"}')
    monkeypatch.setattr(cli, "_tool", lambda *_: None)
    assert cli.print_doctor(True) == 2
    assert "secret-cookie-path" not in capsys.readouterr().out


def test_doctor_reports_tool_versions_without_network(monkeypatch, tmp_path):
    import subprocess
    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(cli, "_tool", lambda name, configured: name if name in {"ffmpeg", "ffprobe"} else None)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, f"{args[0]} version test\nextra", "")
    monkeypatch.setattr(cli.subprocess, "run", run)
    report, code = cli.doctor()
    assert code == 0
    assert report["checks"]["ffmpeg_version"] == "ffmpeg version test"
    assert report["checks"]["ffprobe_version"] == "ffprobe version test"
    assert calls == [["ffmpeg", "-version"], ["ffprobe", "-version"]]


def test_doctor_redacts_tool_help(monkeypatch, tmp_path, capsys):
    import subprocess
    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(cli, "_tool", lambda name, configured: name if name == "mp3gain" else None)
    monkeypatch.setattr(cli.subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(args, 0, 'mp3gain help\ncookiefile="C:\\private path\\cookies.txt" token=secret-value', ""))
    assert cli.print_doctor(True) == 0
    output = capsys.readouterr().out
    assert "private path" not in output and "secret-value" not in output
