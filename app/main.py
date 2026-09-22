"""Punto de entrada de Dossier Builder QA/QC.

Ejecutar con:  python main.py   (desde la raiz del repositorio)
"""
from __future__ import annotations

import sys
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox

from app.services.logger import setup_logging, get_logger
from app.services.settings import SettingsService
from app.ui.theme import apply_theme

logger = get_logger("main")


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

    settings_service = SettingsService()
    apply_theme(app, settings_service.settings.theme)

    from app.ui.main_window import MainWindow  # import diferido: requiere QApplication ya creada

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
