"""Operaciones de bajo nivel sobre PDF: apertura, TOC/bookmarks, insercion, guardado.

Toda la manipulacion de paginas usa PyMuPDF (fitz). Este modulo no conoce el
modelo de Proyecto/Seccion: trabaja con rutas de archivo y estructuras
simples (listas/tuplas) para poder probarse de forma aislada.
"""
from __future__ import annotations

import re
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


def insert_pdf_pages(dest_doc: fitz.Document, insert_path: str, at_index: int) -> int:
    """Inserta todas las paginas de ``insert_path`` en ``dest_doc`` en la posicion ``at_index``.

    Devuelve la cantidad de paginas insertadas. ``at_index`` sigue la
    convencion de PyMuPDF: las paginas insertadas quedan *despues* de la
    pagina ``at_index - 1`` (es decir, antes de lo que hoy es la pagina
    ``at_index``). Usar ``at_index = dest_doc.page_count`` para agregar al final.
    """
    src_doc = open_document(insert_path)
    try:
        count = src_doc.page_count
        dest_doc.insert_pdf(src_doc, start_at=at_index)
        return count
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
