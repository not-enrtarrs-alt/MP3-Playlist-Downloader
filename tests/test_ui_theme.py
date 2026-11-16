"""Contrast checks for palette transitions and native-looking widgets."""

import pytest
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton

from mp3_playlist_downloader.ui.theme import apply_theme, is_dark
from mp3_playlist_downloader.ui.track_model import DARK, LIGHT


def contrast(first: QColor, second: QColor) -> float:
    def luminance(color: QColor) -> float:
        channels = [color.redF(), color.greenF(), color.blueF()]
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


@pytest.fixture
def restore_theme(qapp):
    palette, stylesheet = QPalette(qapp.palette()), qapp.styleSheet()
    yield
    qapp.setStyleSheet(stylesheet)
    qapp.setPalette(palette)


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_palette_text_contrast_for_all_primary_surfaces(qapp, qtbot, restore_theme, mode):
    apply_theme(qapp, mode)
    palette = qapp.palette()
    for foreground, background in (
        (QPalette.ColorRole.WindowText, QPalette.ColorRole.Window),
        (QPalette.ColorRole.Text, QPalette.ColorRole.Base),
        (QPalette.ColorRole.ButtonText, QPalette.ColorRole.Button),
        (QPalette.ColorRole.HighlightedText, QPalette.ColorRole.Highlight),
        (QPalette.ColorRole.ToolTipText, QPalette.ColorRole.ToolTipBase),
    ):
        assert contrast(palette.color(foreground), palette.color(background)) >= 4.5
    for widget in (QLabel("Label"), QLineEdit("Input"), QPushButton("Button")):
        qtbot.addWidget(widget)
        widget.show()
        role = QPalette.ColorRole.ButtonText if isinstance(widget, QPushButton) else QPalette.ColorRole.Text if isinstance(widget, QLineEdit) else QPalette.ColorRole.WindowText
        background = QPalette.ColorRole.Button if isinstance(widget, QPushButton) else QPalette.ColorRole.Base if isinstance(widget, QLineEdit) else QPalette.ColorRole.Window
        assert contrast(widget.palette().color(role), widget.palette().color(background)) >= 4.5


def test_switch_from_dark_to_light_restores_dark_text(qapp, restore_theme):
    apply_theme(qapp, "dark")
    apply_theme(qapp, "light")
    palette = qapp.palette()
    assert palette.color(QPalette.ColorRole.WindowText).name() == "#202124"
    assert palette.color(QPalette.ColorRole.Text).name() == "#202124"
    assert palette.color(QPalette.ColorRole.ButtonText).name() == "#202124"
    assert palette.color(QPalette.ColorRole.Base).name() == "#ffffff"
    assert "color: #202124" in qapp.styleSheet()


def test_system_resolves_qt_color_scheme(qapp, restore_theme):
    from PySide6.QtCore import Qt
    assert is_dark(qapp, "system") == (qapp.styleHints().colorScheme() == Qt.ColorScheme.Dark)


def test_status_colors_remain_readable_on_normal_background(qapp, restore_theme):
    for mode, colors in (("light", LIGHT), ("dark", DARK)):
        apply_theme(qapp, mode)
        for value in colors.values():
            for role in (QPalette.ColorRole.Base, QPalette.ColorRole.Highlight):
                assert contrast(QColor(value), qapp.palette().color(role)) >= 4.5


def test_status_foreground_is_not_erased_by_light_stylesheet(qapp, qtbot, restore_theme):
    from mp3_playlist_downloader.ui.track_model import TrackModel
    from mp3_playlist_downloader.ui.track_table import TrackTable

    apply_theme(qapp, "light")
    model = TrackModel(dark=False)
    model.set_rows([{"title": "MMMMMMMMMMMMMMMM", "position": 0}])
    table = TrackTable(model)
    qtbot.addWidget(table)
    table.resize(900, 200)
    table.show()
    qtbot.waitExposed(table)
    image = table.viewport().grab().toImage()
    expected = QColor(LIGHT["red"]).rgb() & 0xFFFFFF
    pixels = {image.pixel(x, y) & 0xFFFFFF for x in range(image.width()) for y in range(image.height())}
    assert expected in pixels


def test_selected_light_status_color_is_visible(qapp, qtbot, restore_theme):
    from mp3_playlist_downloader.ui.track_model import TrackModel
    from mp3_playlist_downloader.ui.track_table import TrackTable

    apply_theme(qapp, "light")
    model = TrackModel(dark=False)
    model.set_rows([{"title": "MMMMMMMMMMMMMMMM", "position": 0}])
    table = TrackTable(model)
    qtbot.addWidget(table)
    table.resize(900, 200)
    table.show()
    table.selectRow(0)
    qtbot.waitExposed(table)
    image = table.viewport().grab().toImage()
    expected = QColor(LIGHT["red"]).rgb() & 0xFFFFFF
    pixels = {image.pixel(x, y) & 0xFFFFFF for x in range(image.width()) for y in range(image.height())}
    assert expected in pixels
