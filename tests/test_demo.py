import os
import subprocess
import sys

from mp3_playlist_downloader import db, demo, library


def test_demo_seed_isolated_and_states(monkeypatch, tmp_path):
    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    summary = demo.seed(tmp_path)
    assert summary == {"green": 2, "blue": 1, "red": 1, "yellow": 1}
    connection = db.connect()
    playlist = db.list_playlists(connection)[0]
    tracks = db.list_videos(connection, playlist["id"])
    assert [row["equalized"] for row in tracks] == [1, 1, 0, 0]
    assert [row["downloaded"] for row in tracks] == [1, 1, 1, 0]
    assert len(library.list_extras(connection, playlist["id"])) == 1
    connection.close()


def test_demo_check_cli_is_offline_and_does_not_touch_user_data(tmp_path):
    env = os.environ.copy()
    env["MP3PD_DATA_DIR"] = str(tmp_path / "real-data")
    result = subprocess.run([sys.executable, "-m", "mp3_playlist_downloader", "demo", "--check"], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "2 green" in result.stdout and "1 yellow" in result.stdout
    assert not (tmp_path / "real-data").exists()


def test_demo_gui_model_shows_all_five_states(qtbot, monkeypatch, tmp_path):
    from mp3_playlist_downloader.settings import load
    from mp3_playlist_downloader.ui.main_window import MainWindow
    from mp3_playlist_downloader.ui.track_model import row_state

    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    demo.seed(tmp_path)
    window = MainWindow(load().settings)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.queue_controller.recovery is None and not window.library_controller.scans, timeout=5000)
    colors = [row_state(row)[1] for row in window.track_model.rows]
    assert colors == ["green", "green", "blue", "red", "yellow"]
    window.close()


def test_demo_check_rejects_incorrect_seed_and_restores_environment(monkeypatch, tmp_path, capsys):
    original = str(tmp_path / "real-data")
    monkeypatch.setenv("MP3PD_DATA_DIR", original)
    monkeypatch.setattr(demo, "seed", lambda root: {"green": 0, "blue": 0, "red": 0, "yellow": 0})
    assert demo.run(check=True) == 2
    assert "0 green" in capsys.readouterr().out
    assert os.environ["MP3PD_DATA_DIR"] == original


def test_demo_works_without_ffmpeg_or_subprocess(monkeypatch, tmp_path, capsys):
    from mp3_playlist_downloader import paths
    monkeypatch.setattr(paths, "find_tool", lambda *args: None)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no subprocess allowed")))
    assert demo.run(check=True) == 0
    assert "2 green" in capsys.readouterr().out
