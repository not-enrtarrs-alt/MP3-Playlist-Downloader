"""Consistent, readable light and dark Qt palettes."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def is_dark(app: QApplication, theme: str) -> bool:
    """Resolve System using Qt's reported color scheme."""
    return theme == "dark" or (theme == "system" and app.styleHints().colorScheme() == Qt.ColorScheme.Dark)


def apply_theme(app: QApplication, theme: str) -> None:
    """Set foreground and background together, even on a dark Windows system."""
    dark = is_dark(app, theme)
    colors = {
        "window": "#202124" if dark else "#f6f7f9",
        "base": "#191a1c" if dark else "#ffffff",
        "button": "#35363a" if dark else "#e9edf3",
        "text": "#f1f3f4" if dark else "#202124",
        "disabled": "#b5b8bd" if dark else "#595d63",
        "highlight": "#1d2024" if dark else "#f4f7ff",
        "link": "#8ab4f8" if dark else "#0053b3",
    }
    palette = QPalette(app.style().standardPalette())
    for role, key in (
        (QPalette.ColorRole.Window, "window"), (QPalette.ColorRole.WindowText, "text"),
        (QPalette.ColorRole.Base, "base"), (QPalette.ColorRole.AlternateBase, "window"),
        (QPalette.ColorRole.Text, "text"), (QPalette.ColorRole.Button, "button"),
        (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.Highlight, "highlight"),
        (QPalette.ColorRole.HighlightedText, "text"), (QPalette.ColorRole.ToolTipBase, "base"),
        (QPalette.ColorRole.ToolTipText, "text"), (QPalette.ColorRole.Link, "link"),
        (QPalette.ColorRole.PlaceholderText, "disabled"),
    ):
        palette.setColor(role, QColor(colors[key]))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors["disabled"]))
    app.setPalette(palette)
    # Native Windows styles can ignore parts of a palette; pair widget colors
    # explicitly without styling table-item text, which carries status colors.
    app.setStyleSheet(f"""
        QLabel, QCheckBox, QRadioButton, QGroupBox {{ color: {colors['text']}; }}
        QLineEdit, QPlainTextEdit, QTextEdit, QListWidget, QTableView, QSpinBox {{
            color: {colors['text']}; background-color: {colors['base']};
            selection-color: {colors['text']}; selection-background-color: {colors['highlight']};
        }}
        QPushButton, QComboBox {{ color: {colors['text']}; background-color: {colors['button']}; }}
        QPushButton:disabled, QComboBox:disabled {{ color: {colors['disabled']}; }}
        QMenu, QToolTip {{ color: {colors['text']}; background-color: {colors['base']}; }}
    """)
