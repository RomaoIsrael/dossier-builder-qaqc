"""Punto de entrada de Dossier Builder QA/QC.

Ejecutar con:  python main.py   (desde la raiz del repositorio)
"""
from __future__ import annotations

import sys
import time
import traceback

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen

from app.services.logger import setup_logging, get_logger
from app.services.settings import SettingsService
from app.ui.theme import apply_theme

logger = get_logger("main")

_SPLASH_WIDTH = 520
_SPLASH_HEIGHT = 340
_SPLASH_STEPS = [
    "Cargando configuracion...",
    "Preparando la interfaz...",
    "Casi listo...",
]
_SPLASH_STEP_SECONDS = 0.4


def _build_splash_pixmap() -> QPixmap:
    """Dibuja la pantalla de bienvenida a mano (sin depender de ningun
    archivo de imagen externo), con un estilo similar al de otros programas
    de escritorio (Word, etc.) al abrirse."""
    from app.ui.dialogs import APP_AUTHOR_NAME, APP_VERSION  # import diferido: evita ciclos al iniciar

    pixmap = QPixmap(_SPLASH_WIDTH, _SPLASH_HEIGHT)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    gradient = QLinearGradient(0, 0, _SPLASH_WIDTH, _SPLASH_HEIGHT)
    gradient.setColorAt(0.0, QColor("#0f2c4c"))
    gradient.setColorAt(1.0, QColor("#1b6fa8"))
    painter.setPen(Qt.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(0, 0, _SPLASH_WIDTH, _SPLASH_HEIGHT, 18, 18)

    painter.setPen(QColor("#ffffff"))
    painter.setFont(QFont("Segoe UI", 22, QFont.Bold))
    painter.drawText(0, 70, _SPLASH_WIDTH, 50, Qt.AlignHCenter, "Dossier Builder QA/QC")

    painter.setPen(QColor("#e3f1fb"))
    painter.setFont(QFont("Segoe UI", 15, QFont.DemiBold))
    painter.drawText(0, 120, _SPLASH_WIDTH, 40, Qt.AlignHCenter, "¡Bienvenido!")

    painter.setPen(QColor("#c3ddef"))
    painter.setFont(QFont("Segoe UI", 10))
    painter.drawText(
        30,
        160,
        _SPLASH_WIDTH - 60,
        60,
        Qt.AlignHCenter | Qt.TextWordWrap,
        "Preparando su espacio de trabajo para armar dossiers de QA/QC...",
    )

    painter.setPen(QColor("#8fb8d6"))
    painter.setFont(QFont("Segoe UI", 8))
    painter.drawText(
        0, _SPLASH_HEIGHT - 70, _SPLASH_WIDTH, 20, Qt.AlignHCenter, f"Version {APP_VERSION}  -  {APP_AUTHOR_NAME}"
    )

    painter.end()
    return pixmap


def _show_splash(app: QApplication) -> QSplashScreen:
    splash = QSplashScreen(_build_splash_pixmap())
    splash.setWindowFlag(Qt.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()

    for message in _SPLASH_STEPS:
        splash.showMessage(
            message, int(Qt.AlignHCenter | Qt.AlignBottom), QColor("#ffffff")
        )
        app.processEvents()
        time.sleep(_SPLASH_STEP_SECONDS)

    return splash


def _install_exception_hook(app: QApplication) -> None:
    """Evita que una excepcion no capturada cierre la aplicacion silenciosamente.

    Muestra un mensaje comprensible al usuario y registra el error completo
    en el log, en vez de dejar que un PDF defectuoso o un error puntual tumbe
    toda la aplicacion (requisito explicito del proyecto).
    """

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.error("Excepcion no controlada:\n%s", "".join(
            traceback.format_exception(exc_type, exc_value, exc_traceback)
        ))
        QMessageBox.critical(
            None,
            "Error inesperado",
            f"Ocurrio un error inesperado:\n\n{exc_value}\n\n"
            "El detalle se guardo en el archivo de log (dossierbuilder.log).",
        )

    sys.excepthook = handle_exception


def main() -> int:
    setup_logging()
    logger.info("Iniciando Dossier Builder QA/QC")

    app = QApplication(sys.argv)
    app.setApplicationName("Dossier Builder QA/QC")
    app.setOrganizationName("DossierBuilderQAQC")

    _install_exception_hook(app)

    splash = _show_splash(app)

    settings_service = SettingsService()
    apply_theme(app, settings_service.settings.theme)

    from app.ui.main_window import MainWindow  # import diferido: requiere QApplication ya creada

    window = MainWindow()
    window.show()
    splash.finish(window)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
