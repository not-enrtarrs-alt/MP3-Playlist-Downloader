from PySide6.QtCore import Qt

from mp3_playlist_downloader.ui.track_model import TrackModel, row_state
from mp3_playlist_downloader.ui.track_table import TrackTable


def test_state_priority_and_accessible_text():
    assert row_state({"downloaded": 1, "equalized": 1, "in_playlist": 0}) == ("Downloaded · equalized", "green")
    assert row_state({"downloaded": 1, "unavailable": 1}) == ("Downloaded", "blue")
    assert row_state({"in_playlist": 0}) == ("Removed from playlist", "grey")
    assert row_state({"_extra": True, "disposition": "kept"}) == ("Extra file · kept", "yellow")
    assert row_state({"download_state": "failed"}) == ("Failed", "red")


def test_model_selection_colors_and_badges(qtbot):
    model = TrackModel()
    model.set_rows([
        {"title": "Artist - Song", "uploader": "Artist - Topic", "is_topic": 1, "position": 0, "duration_seconds": 62},
        {"title": "Removed", "position": 2, "downloaded": 1, "in_playlist": 0},
    ])
    table = TrackTable(model)
    qtbot.addWidget(table)
    assert model.index(0, 2).data() == "Song  [Topic]"
    assert model.index(0, 3).data() == "1:02"
    assert model.index(0, 2).data(Qt.ItemDataRole.ForegroundRole).name() == "#c62828"
    assert model.index(1, 2).data(Qt.ItemDataRole.ForegroundRole).name() == "#1565c0"
    model.setData(model.index(0, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert model.check_state() == Qt.CheckState.PartiallyChecked
    model.set_all(True)
    assert model.check_state() == Qt.CheckState.Checked
    model.set_all(False)
    assert model.check_state() == Qt.CheckState.Unchecked
    model.set_rows([{"title": "New"}])
    assert not model.checked
