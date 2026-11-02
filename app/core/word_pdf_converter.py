"""Conversion de un .docx a PDF usando Microsoft Word instalado en la maquina.

Se usa para convertir la plantilla LDSS (y, a futuro, otras) ya completada
con los datos del proyecto (ver app.core.template_filler) a un PDF listo
para usarse como ``project.template_path``. Los encabezados Word ("Heading
1"/"Heading 2") se convierten en marcadores del PDF automaticamente durante
esta conversion: es el propio Word el que lo hace, no se construye nada a
mano aqui.

Requiere Microsoft Word instalado en la maquina (Windows unicamente, via
automatizacion COM con ``pywin32``) -- no hay forma de evitar esta
dependencia si se quiere la maxima fidelidad con el diseno original del
Word (logos, resaltados, posicion exacta de los cuadros de texto de la
caratula del CD, etc.), que un conversor generico no replicaria igual.
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.services.logger import get_logger

logger = get_logger("word_pdf_converter")

# Valor de wdExportFormat para PDF en la automatizacion COM de Word
# (constante estable de la API de Word, no cambia entre versiones).
_WD_EXPORT_FORMAT_PDF = 17


class WordConversionError(Exception):
    """No se pudo convertir el .docx a PDF usando Microsoft Word."""


def convert_docx_to_pdf_with_word(docx_path: str, pdf_path: str) -> str:
    """Abre ``docx_path`` con Microsoft Word (automatizacion COM, en
    segundo plano, sin mostrar la ventana de Word) y lo exporta como PDF en
    ``pdf_path``. Cierra Word al terminar, incluso si algo falla a mitad de
    camino, para no dejar procesos de Word huerfanos corriendo.
    """
    if sys.platform != "win32":
        raise WordConversionError(
            "La conversion automatica de Word a PDF solo funciona en Windows "
            "(requiere Microsoft Word instalado). En este sistema no esta disponible."
        )

    try:
        import win32com.client  # type: ignore[import-not-found]
    except ImportError as exc:
        raise WordConversionError(
            "Falta el paquete 'pywin32' (automatizacion de Microsoft Word). "
            "Instalar dependencias de nuevo con install.bat deberia resolverlo."
        ) from exc

    docx_abs = str(Path(docx_path).resolve())
    pdf_abs = str(Path(pdf_path).resolve())
    Path(pdf_abs).parent.mkdir(parents=True, exist_ok=True)

    word = None
    document = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0  # wdAlertsNone: no mostrar dialogos (ej. "formato no compatible")
        document = word.Documents.Open(docx_abs, ReadOnly=True)
        document.ExportAsFixedFormat(pdf_abs, ExportFormat=_WD_EXPORT_FORMAT_PDF)
    except Exception as exc:  # noqa: BLE001 - cualquier error de COM/Word se traduce a un mensaje claro
        raise WordConversionError(
            f"No se pudo convertir '{docx_path}' a PDF con Microsoft Word: {exc}. "
            "Verificar que Microsoft Word este instalado y con licencia activa en esta computadora."
        ) from exc
    finally:
        try:
            if document is not None:
                document.Close(False)
        except Exception:  # noqa: BLE001 - cerrar en limpio es best-effort
            logger.warning("No se pudo cerrar el documento de Word de forma prolija tras la conversion")
        try:
            if word is not None:
                word.Quit()
        except Exception:  # noqa: BLE001
            logger.warning("No se pudo cerrar Microsoft Word de forma prolija tras la conversion")

    if not Path(pdf_abs).exists():
        raise WordConversionError(
            f"Word no reporto error, pero el PDF no quedo creado en '{pdf_abs}'."
        )

    logger.info("Plantilla convertida a PDF con Microsoft Word: '%s' -> '%s'", docx_path, pdf_path)
    return pdf_abs
