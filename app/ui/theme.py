"""Tema claro/oscuro de la aplicacion (hoja de estilos Qt/QSS)."""
from __future__ import annotations

LIGHT_STYLESHEET = ""  # el tema claro es el estilo nativo de Qt, sin hoja de estilos propia

DARK_STYLESHEET = """
QWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
    selection-background-color: #094771;
    selection-color: #ffffff;
}
QMainWindow, QDialog {
    background-color: #1e1e1e;
}
QToolBar {
    background-color: #252526;
    border: none;
    spacing: 4px;
    padding: 4px;
}
QToolBar QToolButton {
    background-color: transparent;
    color: #e0e0e0;
    padding: 4px 8px;
    border-radius: 3px;
}
QToolBar QToolButton:hover {
    background-color: #3a3d41;
}
QPushButton {
    background-color: #3a3d41;
    color: #e0e0e0;
    border: 1px solid #555555;
    padding: 5px 10px;
    border-radius: 3px;
}
QPushButton:hover {
    background-color: #45494e;
}
QPushButton:pressed {
    background-color: #094771;
}
QPushButton:disabled {
    color: #7a7a7a;
    border-color: #3f3f3f;
}
QLineEdit, QComboBox, QSpinBox, QListWidget, QTreeWidget, QTableWidget, QPlainTextEdit {
    background-color: #252526;
    color: #e0e0e0;
    border: 1px solid #3f3f3f;
    border-radius: 2px;
}
QTreeWidget::item:selected, QListWidget::item:selected, QTableWidget::item:selected {
    background-color: #094771;
}
QHeaderView::section {
    background-color: #2d2d30;
    color: #e0e0e0;
    border: 1px solid #3f3f3f;
    padding: 4px;
}
QMenu {
    background-color: #252526;
    color: #e0e0e0;
    border: 1px solid #3f3f3f;
}
QMenu::item:selected {
    background-color: #094771;
}
QStatusBar {
    background-color: #007acc;
    color: #ffffff;
}
QLabel {
    color: #e0e0e0;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background: #1e1e1e;
}
QProgressDialog, QMessageBox {
    background-color: #252526;
}
"""


def apply_theme(app, theme: str) -> None:
    """Aplica el tema ("light" | "dark") a toda la aplicacion Qt."""
    app.setStyleSheet(DARK_STYLESHEET if theme == "dark" else LIGHT_STYLESHEET)
