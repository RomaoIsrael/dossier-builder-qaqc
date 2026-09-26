"""Operaciones de bajo nivel sobre PDF: apertura, TOC/bookmarks, insercion, guardado.

Toda la manipulacion de paginas usa PyMuPDF (fitz). Este modulo no conoce el
modelo de Proyecto/Seccion: trabaja con rutas de archivo y estructuras
simples (listas/tuplas) para poder probarse de forma aislada.
"""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from typing import Optional

import fitz  # PyMuPDF

from app.services.logger import get_logger

logger = get_logger("pdf_engine")

_NUMBERING_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+(.*)$")


class PDFOpenError(Exception):
    """No se pudo abrir o leer un PDF."""


class PDFPasswordProtectedError(PDFOpenError):
    """El PDF requiere una contrasena que no fue provista o es incorrecta."""


@dataclass
class TocEntry:
    level: int
    title: str
    page_index: int  # 0-based
    numbering: str = ""
    clean_title: str = ""

    def __post_init__(self) -> None:
        match = _NUMBERING_RE.match(self.title.strip())
        if match:
            self.numbering = match.group(1)
            self.clean_title = match.group(2).strip()
        else:
            self.clean_title = self.title.strip()


def open_document(path: str, password: Optional[str] = None) -> fitz.Document:
    """Abre un PDF y lanza errores especificos y comprensibles si falla."""
    try:
        doc = fitz.open(path)
    except Exception as exc:  # PyMuPDF lanza excepciones genericas de fitz
        raise PDFOpenError(f"No se pudo abrir '{path}': {exc}") from exc

    if doc.is_encrypted:
        ok = False
        if password:
            ok = doc.authenticate(password) != 0
        if not ok:
            doc.close()
            raise PDFPasswordProtectedError(
                f"'{path}' esta protegido con contrasena y no se pudo abrir."
            )
    return doc


def get_page_count(path: str) -> int:
    doc = open_document(path)
    try:
        return doc.page_count
    finally:
        doc.close()


def is_pdf_readable(path: str) -> tuple[bool, Optional[str]]:
    """Verifica que un PDF se pueda abrir y tenga al menos una pagina.

    Devuelve (ok, mensaje_error_o_None).
    """
    try:
        doc = open_document(path)
        try:
            if doc.page_count <= 0:
                return False, "El PDF no tiene paginas."
            return True, None
        finally:
            doc.close()
    except PDFPasswordProtectedError as exc:
        return False, str(exc)
    except PDFOpenError as exc:
        return False, str(exc)


def extract_toc(path: str) -> list[TocEntry]:
    """Extrae los bookmarks (tabla de contenidos) de un PDF de plantilla."""
    doc = open_document(path)
    try:
        raw = doc.get_toc(simple=True)  # [[level, title, page(1-based)], ...]
    finally:
        doc.close()
    return [TocEntry(level=lvl, title=title, page_index=page - 1) for lvl, title, page in raw]


def _repair_pdf_copy(path: str) -> Optional[str]:
    """Intenta reescribir un PDF a un archivo temporal para reparar
    estructuras internas danadas (tablas xref/numeros de objeto rotos,
    tipico en PDF escaneados o que ya pasaron por otras herramientas de
    combinacion). Reabrir y volver a guardar con PyMuPDF fuerza una
    reconstruccion completa de esas estructuras.

    Devuelve la ruta del archivo reparado, o ``None`` si no se pudo reparar
    (en cuyo caso el llamador debe reportar el error original).
    """
    try:
        doc = fitz.open(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo reparar '%s': no se pudo reabrir (%s)", path, exc)
        return None
    try:
        fd, temp_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        doc.save(temp_path, garbage=4, clean=True, deflate=True)
        return temp_path
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo reparar '%s': fallo al reescribir (%s)", path, exc)
        return None
    finally:
        doc.close()


def insert_pdf_pages(
    dest_doc: fitz.Document, insert_path: str, at_index: int, excluded_pages: Optional[set[int]] = None
) -> int:
    """Inserta las paginas de ``insert_path`` en ``dest_doc`` en la posicion ``at_index``.

    Devuelve la cantidad de paginas insertadas. ``at_index`` sigue la
    convencion de PyMuPDF: las paginas insertadas quedan *despues* de la
    pagina ``at_index - 1`` (es decir, antes de lo que hoy es la pagina
    ``at_index``). Usar ``at_index = dest_doc.page_count`` para agregar al final.

    Si se pasa ``excluded_pages`` (indices 0-based sobre ``insert_path``), esas
    paginas se omiten (por ejemplo, una hoja que el usuario marco para no
    incluir en el dossier desde el panel de miniaturas). Si con eso no
    quedara ninguna pagina por insertar, no se inserta nada y se devuelve 0.

    Si la insercion directa falla por un error de bajo nivel de PyMuPDF
    (por ejemplo "source object number out of range", tipico de PDF con
    estructuras internas danadas), se intenta reparar una copia del origen
    reescribiendolo desde cero y se reintenta una vez desde esa copia antes
    de darse por vencido.
    """

    def select_included_pages(doc: fitz.Document) -> int:
        """Si hay paginas excluidas validas, reduce ``doc`` en el lugar a solo
        las paginas restantes (en orden). Devuelve cuantas quedaron."""
        if not excluded_pages:
            return doc.page_count
        keep = [i for i in range(doc.page_count) if i not in excluded_pages]
        if not keep:
            return 0
        if len(keep) != doc.page_count:
            doc.select(keep)
        return doc.page_count

    src_doc = open_document(insert_path)
    try:
        count = select_included_pages(src_doc)
        if count == 0:
            return 0
        dest_doc.insert_pdf(src_doc, start_at=at_index)
        return count
    except Exception as exc:  # noqa: BLE001 - incluye errores de bajo nivel de PyMuPDF
        logger.warning(
            "Fallo al insertar '%s' directamente (%s); intentando reparar y reintentar...", insert_path, exc
        )
        repaired_path = _repair_pdf_copy(insert_path)
        if repaired_path is None:
            raise PDFOpenError(f"No se pudo insertar '{insert_path}': {exc}") from exc
        try:
            repaired_doc = open_document(repaired_path)
            try:
                count = select_included_pages(repaired_doc)
                if count == 0:
                    return 0
                dest_doc.insert_pdf(repaired_doc, start_at=at_index)
                logger.info("Reparacion exitosa: '%s' se pudo insertar tras reescribirlo.", insert_path)
                return count
            finally:
                repaired_doc.close()
        except Exception as exc2:  # noqa: BLE001
            raise PDFOpenError(
                f"No se pudo insertar '{insert_path}' incluso despues de intentar repararlo: {exc2}"
            ) from exc2
        finally:
            try:
                os.unlink(repaired_path)
            except OSError:
                pass
    finally:
        src_doc.close()


def new_empty_document() -> fitz.Document:
    return fitz.open()


def copy_document(path: str) -> fitz.Document:
    """Abre una copia en memoria de un PDF para usar como base del ensamblado."""
    src = open_document(path)
    try:
        clone = fitz.open()
        clone.insert_pdf(src)
        return clone
    finally:
        src.close()


def set_toc(doc: fitz.Document, toc: list[list]) -> None:
    """Aplica una tabla de contenidos. ``toc`` es una lista [nivel, titulo, pagina(1-based)]."""
    doc.set_toc(toc)


def set_metadata(doc: fitz.Document, metadata: dict) -> None:
    current = doc.metadata or {}
    current.update({k: v for k, v in metadata.items() if v})
    doc.set_metadata(current)


def save_document(doc: fitz.Document, output_path: str, optimize: bool = True) -> None:
    doc.save(
        output_path,
        garbage=4 if optimize else 0,
        deflate=True,
        clean=True,
    )
    logger.info("PDF guardado: %s (%d paginas)", output_path, doc.page_count)


def get_page_size_and_rotation(path: str, page_index: int = 0) -> tuple[float, float, int]:
    doc = open_document(path)
    try:
        page = doc[page_index]
        rect = page.rect
        return rect.width, rect.height, page.rotation
    finally:
        doc.close()
