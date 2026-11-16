import logging

from mp3_playlist_downloader.logging_setup import LogBridge, redact, setup_logging


def test_redaction():
    text = 'Cookie: sensitive-session\ntoken=secret&cookies_file="C:\\private path\\cookies.txt"'
    result = redact(text)
    assert "sensitive-session" not in result
    assert "secret" not in result
    assert "private path" not in result


def test_file_and_qt_bridge_redact(monkeypatch, tmp_path, qtbot):
    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path))
    bridge = LogBridge()
    lines = []
    bridge.line.connect(lines.append)
    setup_logging(bridge)
    logging.getLogger("mp3_playlist_downloader.test").warning("token=%s", "sensitive-value")
    assert lines and "sensitive-value" not in lines[0]
    assert "sensitive-value" not in (tmp_path / "logs" / "app.log").read_text()
