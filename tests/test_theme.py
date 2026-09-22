"""app/ui/theme.py no importa PySide6 (solo llama app.setStyleSheet), asi
que se puede probar con un objeto falso en vez de una QApplication real.
"""
from app.ui.theme import DARK_STYLESHEET, LIGHT_STYLESHEET, apply_theme


class _FakeApp:
    def __init__(self):
        self.stylesheet = "sin_tocar"

    def setStyleSheet(self, css: str) -> None:
        self.stylesheet = css


def test_light_and_dark_stylesheets_are_non_empty_and_different():
    assert LIGHT_STYLESHEET.strip() != ""
    assert DARK_STYLESHEET.strip() != ""
    assert LIGHT_STYLESHEET != DARK_STYLESHEET


def test_apply_theme_dark_sets_dark_stylesheet():
    app = _FakeApp()
    apply_theme(app, "dark")
    assert app.stylesheet == DARK_STYLESHEET


def test_apply_theme_light_sets_light_stylesheet():
    app = _FakeApp()
    apply_theme(app, "light")
    assert app.stylesheet == LIGHT_STYLESHEET


def test_apply_theme_unknown_value_falls_back_to_light():
    app = _FakeApp()
    apply_theme(app, "algo-invalido")
    assert app.stylesheet == LIGHT_STYLESHEET
