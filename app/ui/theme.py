"""Tema visual de la aplicacion (hojas de estilo Qt/QSS), claro y oscuro.

Ambos temas comparten la misma estructura de reglas (mismos selectores),
solo cambia la paleta de colores, para que sea facil mantenerlos en
paralelo si se agrega un widget nuevo.
"""
from __future__ import annotations


def _build_stylesheet(colors: dict[str, str]) -> str:
    c = colors
    return f"""
QWidget {{
    background-color: {c['bg']};
    color: {c['text']};
    font-family: "Segoe UI", "Cantarell", sans-serif;
    font-size: 10pt;
    selection-background-color: {c['accent']};
    selection-color: {c['accent_text']};
}}

QMainWindow, QDialog {{
    background-color: {c['bg']};
}}

/* -- Barra de herramientas ------------------------------------------- */
QToolBar {{
    background-color: {c['panel']};
    border: none;
    border-bottom: 1px solid {c['border']};
    padding: 6px 8px;
    spacing: 4px;
}}
QToolBar QToolButton {{
    background-color: transparent;
    color: {c['text']};
    padding: 6px 10px;
    border-radius: 6px;
    font-weight: 500;
}}
QToolBar QToolButton:hover {{
    background-color: {c['accent_soft']};
    color: {c['accent']};
}}
QToolBar QToolButton:pressed {{
    background-color: {c['accent']};
    color: {c['accent_text']};
}}
QToolBar::separator {{
    background-color: {c['border']};
    width: 1px;
    margin: 6px 6px;
}}

/* -- Botones ------------------------------------------------------------- */
QPushButton {{
    background-color: {c['button_bg']};
    color: {c['text']};
    border: 1px solid {c['border']};
    padding: 6px 14px;
    border-radius: 6px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {c['accent_soft']};
    border-color: {c['accent']};
    color: {c['accent']};
}}
QPushButton:pressed {{
    background-color: {c['accent']};
    color: {c['accent_text']};
    border-color: {c['accent']};
}}
QPushButton:disabled {{
    color: {c['text_muted']};
    border-color: {c['border']};
    background-color: {c['panel']};
}}

/* -- Campos de entrada ------------------------------------------------ */
QLineEdit, QComboBox, QSpinBox {{
    background-color: {c['panel']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 5px;
    padding: 4px 8px;
    min-height: 22px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border: 1px solid {c['accent']};
}}
QLineEdit:disabled, QComboBox:disabled {{
    color: {c['text_muted']};
    background-color: {c['bg']};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {c['panel']};
    color: {c['text']};
    border: 1px solid {c['border']};
    selection-background-color: {c['accent']};
    selection-color: {c['accent_text']};
    outline: none;
}}
QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {c['border']};
    border-radius: 3px;
    background-color: {c['panel']};
}}
QCheckBox::indicator:checked {{
    background-color: {c['accent']};
    border-color: {c['accent']};
}}

/* -- Listas, arboles y tablas ------------------------------------------ */
QTreeWidget, QListWidget, QTableWidget {{
    background-color: {c['panel']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    alternate-background-color: {c['bg']};
    outline: none;
    padding: 2px;
}}
QTreeWidget::item, QListWidget::item {{
    padding: 4px 2px;
    border-radius: 4px;
}}
QTableWidget::item {{
    padding: 3px;
}}
QTreeWidget::item:hover, QListWidget::item:hover, QTableWidget::item:hover {{
    background-color: {c['accent_soft']};
}}
QTreeWidget::item:selected, QListWidget::item:selected, QTableWidget::item:selected {{
    background-color: {c['accent']};
    color: {c['accent_text']};
}}
QHeaderView::section {{
    background-color: {c['panel_alt']};
    color: {c['text_muted']};
    border: none;
    border-bottom: 1px solid {c['border']};
    border-right: 1px solid {c['border']};
    padding: 6px 8px;
    font-weight: 600;
}}
QTreeView::branch {{
    background-color: transparent;
}}

/* -- Menus y tooltips --------------------------------------------------- */
QMenu {{
    background-color: {c['panel']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {c['accent']};
    color: {c['accent_text']};
}}
QToolTip {{
    background-color: {c['panel_alt']};
    color: {c['text']};
    border: 1px solid {c['border']};
    padding: 4px 6px;
    border-radius: 4px;
}}

/* -- Barra de estado y progreso ------------------------------------------ */
QStatusBar {{
    background-color: {c['accent']};
    color: {c['accent_text']};
}}
QStatusBar QLabel {{
    color: {c['accent_text']};
}}
QProgressBar {{
    background-color: {c['panel_alt']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    text-align: center;
    color: {c['text']};
}}
QProgressBar::chunk {{
    background-color: {c['accent']};
    border-radius: 5px;
}}

/* -- Separadores y scrollbars -------------------------------------------- */
QSplitter::handle {{
    background-color: {c['border']};
}}
QSplitter::handle:hover {{
    background-color: {c['accent']};
}}
QScrollBar:vertical, QScrollBar:horizontal {{
    background: {c['bg']};
    border: none;
    margin: 0px;
}}
QScrollBar:vertical {{
    width: 12px;
}}
QScrollBar:horizontal {{
    height: 12px;
}}
QScrollBar::handle {{
    background: {c['scrollbar_handle']};
    border-radius: 5px;
    min-height: 24px;
    min-width: 24px;
}}
QScrollBar::handle:hover {{
    background: {c['accent']};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0px;
    width: 0px;
}}

QLabel {{
    color: {c['text']};
}}
"""


_LIGHT_COLORS = {
    "bg": "#f3f5f8",
    "panel": "#ffffff",
    "panel_alt": "#eef1f6",
    "border": "#dde1e8",
    "text": "#1c2430",
    "text_muted": "#8a919e",
    "button_bg": "#ffffff",
    "accent": "#2563eb",
    "accent_soft": "#e5edfd",
    "accent_text": "#ffffff",
    "scrollbar_handle": "#c9ced8",
}

_DARK_COLORS = {
    "bg": "#1a1b1e",
    "panel": "#232428",
    "panel_alt": "#2a2c31",
    "border": "#383a40",
    "text": "#e5e7eb",
    "text_muted": "#8b8f98",
    "button_bg": "#2a2c31",
    "accent": "#3b82f6",
    "accent_soft": "#28354c",
    "accent_text": "#ffffff",
    "scrollbar_handle": "#44464d",
}

LIGHT_STYLESHEET = _build_stylesheet(_LIGHT_COLORS)
DARK_STYLESHEET = _build_stylesheet(_DARK_COLORS)


def apply_theme(app, theme: str) -> None:
    """Aplica el tema ("light" | "dark") a toda la aplicacion Qt."""
    app.setStyleSheet(DARK_STYLESHEET if theme == "dark" else LIGHT_STYLESHEET)
