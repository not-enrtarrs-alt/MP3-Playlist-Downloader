"""Status legend and cached playlist/selection totals."""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .track_model import DARK, LIGHT


class LegendPanel(QWidget):
    def __init__(self, dark: bool = False, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Legend"))
        self.entries = []
        for color, label in (("green", "Downloaded · equalized"), ("blue", "Downloaded"), ("red", "Not downloaded / failed"), ("yellow", "Extra file"), ("grey", "Unavailable / removed")):
            widget = QLabel()
            widget.setWordWrap(True)
            layout.addWidget(widget)
            self.entries.append((widget, color, label))
        self.set_dark(dark)
        self.stats = QLabel("Selection: 0\n0 tracks\n0 downloaded\n0 equalized\n0 extra files")
        layout.addWidget(self.stats)
        layout.addStretch()

    def set_dark(self, dark: bool) -> None:
        colors = DARK if dark else LIGHT
        for widget, color, label in self.entries:
            widget.setText(f'<span style="color:{colors[color]}">●</span> {label}')

    def update_stats(self, rows, selected: int) -> None:
        tracks = [row for row in rows if not row.get("_extra")]
        self.stats.setText(f"Selection: {selected}\n{len(tracks)} tracks\n{sum(bool(row.get('downloaded')) for row in tracks)} downloaded\n{sum(bool(row.get('equalized')) for row in tracks)} equalized\n{len(rows) - len(tracks)} extra files")
