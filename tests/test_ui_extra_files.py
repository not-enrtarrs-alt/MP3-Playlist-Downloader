from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from mp3_playlist_downloader import db, library
from mp3_playlist_downloader.models import PlaylistMetadata
from mp3_playlist_downloader.ui.extra_files_dialog import ExtraFilesDialog


def make_playlist(monkeypatch, tmp_path):
    monkeypatch.setenv("MP3PD_DATA_DIR", str(tmp_path / "data"))
    connection = db.connect()
    db.initialize(connection)
    pid, _ = db.add_playlist(connection, "url", PlaylistMetadata("Playlist", ()), tmp_path / "music")
    folder = tmp_path / "music" / "Playlist"
    (folder / "extra.mp3").write_bytes(b"data")
    library.scan_folder(connection, pid)
    connection.close()
    return pid, folder


def test_dialog_defaults_unselected_and_keep(qtbot, monkeypatch, tmp_path):
    pid, folder = make_playlist(monkeypatch, tmp_path)
    dialog = ExtraFilesDialog(pid)
    qtbot.addWidget(dialog)
    assert dialog.list.count() == 1
    assert dialog.list.item(0).checkState() == Qt.CheckState.Unchecked
    dialog.list.item(0).setCheckState(Qt.CheckState.Checked)
    with qtbot.waitSignal(dialog.accepted, timeout=5000):
        dialog.keep_button.click()
    connection = db.connect()
    assert library.list_extras(connection, pid)[0]["disposition"] == "kept"
    connection.close()
    assert (folder / "extra.mp3").exists()


def test_dialog_delete_requires_confirmation_and_uses_recycler(qtbot, monkeypatch, tmp_path):
    pid, folder = make_playlist(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(library, "send2trash", calls.append)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    dialog = ExtraFilesDialog(pid)
    qtbot.addWidget(dialog)
    dialog.list.item(0).setCheckState(Qt.CheckState.Checked)
    with qtbot.waitSignal(dialog.accepted, timeout=5000):
        dialog.delete_button.click()
    assert calls == [str(folder / "extra.mp3")]
    connection = db.connect()
    assert library.list_extras(connection, pid) == []
    connection.close()
