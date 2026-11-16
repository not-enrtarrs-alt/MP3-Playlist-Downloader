from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from mp3_playlist_downloader.settings import Settings
from mp3_playlist_downloader.ui.add_playlist_dialog import AddPlaylistDialog
from mp3_playlist_downloader.ui.legend_panel import LegendPanel
from mp3_playlist_downloader.ui.playlist_sidebar import PlaylistSidebar
from mp3_playlist_downloader.ui.track_model import TrackModel
from mp3_playlist_downloader.ui.track_table import TrackTable


def test_add_dialog_validation_offline(qtbot, tmp_path):
    dialog = AddPlaylistDialog(Settings(output_root=str(tmp_path)))
    qtbot.addWidget(dialog)
    dialog.url.setText("youtube.com/watch?v=123")
    dialog.start()
    assert "single video" in dialog.message.text()
    assert dialog.worker is None and dialog.result() != QDialog.DialogCode.Accepted


def test_sidebar_selection_and_legend(qtbot):
    sidebar = PlaylistSidebar()
    legend = LegendPanel()
    qtbot.addWidget(sidebar)
    qtbot.addWidget(legend)
    items = [{"id": 1, "title": "One", "track_count": 2, "downloaded_count": 1, "url": "https://example.test"}, {"id": 2, "title": "Two", "track_count": 0, "downloaded_count": 0, "url": "https://example.test"}]
    sidebar.populate(items)
    with qtbot.waitSignal(sidebar.selected, timeout=1000) as signal:
        sidebar.list.setCurrentRow(1)
    assert signal.args == [2]
    assert "2 tracks · 1 downloaded" in sidebar.list.item(0).text()
    legend.update_stats([{"downloaded": 1, "equalized": 1}, {"_extra": True}], 1)
    assert "1 equalized" in legend.stats.text() and "1 extra files" in legend.stats.text()


def test_table_keyboard_selection(qtbot):
    model = TrackModel()
    model.set_rows([{"title": "One"}, {"title": "Two"}])
    table = TrackTable(model)
    qtbot.addWidget(table)
    table.show()
    table.setCurrentIndex(model.index(0, 2))
    qtbot.keyClick(table, Qt.Key.Key_Space)
    assert model.check_state() == Qt.CheckState.PartiallyChecked
    qtbot.keyClick(table, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert model.check_state() == Qt.CheckState.Checked


def test_header_checkbox_toggles_all(qtbot):
    from PySide6.QtCore import QPoint

    model = TrackModel()
    model.set_rows([{"title": "One"}, {"title": "Two"}])
    table = TrackTable(model)
    qtbot.addWidget(table)
    table.show()
    header = table.horizontalHeader()
    qtbot.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(12, header.height() // 2))
    assert model.check_state() == Qt.CheckState.Checked
    qtbot.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(12, header.height() // 2))
    assert model.check_state() == Qt.CheckState.Unchecked


def test_add_dialog_cancel_discards_worker_result(qtbot, monkeypatch, tmp_path):
    import threading
    from PySide6.QtCore import QThreadPool
    from mp3_playlist_downloader import db
    from mp3_playlist_downloader.youtube import client

    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    connection = db.connect()
    db.initialize(connection)
    connection.close()
    entered, release = threading.Event(), threading.Event()
    class SlowFake:
        def __init__(self, options):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            entered.set()
            release.wait(5)
            return {"title": "Not saved", "entries": [{"id": "aaaaaaaaaaa", "title": "Song"}]}
    monkeypatch.setattr(client.yt_dlp, "YoutubeDL", SlowFake)
    dialog = AddPlaylistDialog(Settings(output_root=str(tmp_path / "music")))
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.url.setText("https://youtube.com/playlist?list=PL123")
    dialog.start()
    qtbot.waitUntil(entered.is_set, timeout=3000)
    dialog.reject()
    release.set()
    assert QThreadPool.globalInstance().waitForDone(5000)
    connection = db.connect()
    assert not db.list_playlists(connection)
    connection.close()


def test_add_dialog_success_and_inline_rate_limit(qtbot, monkeypatch, tmp_path):
    from mp3_playlist_downloader import db
    from mp3_playlist_downloader.youtube import client

    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    connection = db.connect()
    db.initialize(connection)
    connection.close()
    class Fake:
        rate_limited = False
        def __init__(self, options):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            if self.rate_limited:
                raise RuntimeError("HTTP Error 429 secret-cookie-path")
            return {"title": "Many tracks", "entries": [{"id": f"video{i:06}", "title": f"Song {i}"} for i in range(200)]}
    monkeypatch.setattr(client.yt_dlp, "YoutubeDL", Fake)
    settings = Settings(output_root=str(tmp_path / "music"))
    dialog = AddPlaylistDialog(settings)
    qtbot.addWidget(dialog)
    dialog.url.setText("youtube.com/playlist?list=PL123")
    with qtbot.waitSignal(dialog.accepted, timeout=5000):
        dialog.start()
    connection = db.connect()
    assert len(db.list_videos(connection, dialog.playlist_id)) == 200
    connection.close()
    Fake.rate_limited = True
    error_dialog = AddPlaylistDialog(settings)
    qtbot.addWidget(error_dialog)
    error_dialog.url.setText("youtube.com/playlist?list=PL456")
    error_dialog.start()
    qtbot.waitUntil(lambda: error_dialog.worker is None, timeout=5000)
    assert "rate-limiting" in error_dialog.message.text()
    assert "secret-cookie-path" not in error_dialog.message.text()
    connection = db.connect()
    assert len(db.list_playlists(connection)) == 1
    connection.close()
