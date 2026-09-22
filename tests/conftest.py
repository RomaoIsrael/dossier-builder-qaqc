"""Fixtures compartidas: generacion de PDFs sinteticos para las pruebas.

Se usa PyMuPDF (fitz) para crear los PDF de prueba, evitando depender de
librerias adicionales (reportlab, etc.) solo para los tests.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest


def _make_pdf(path: Path, page_count: int = 1, label: str = "", width: float = 200, height: float = 280) -> Path:
    doc = fitz.open()
    for i in range(page_count):
        page = doc.new_page(width=width, height=height)
        text = f"{label} - pagina {i + 1}" if label else f"pagina {i + 1}"
        page.insert_text((20, 40), text, fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def make_pdf(tmp_path):
    counter = {"n": 0}

    def _factory(page_count: int = 1, label: str = "", name: str | None = None) -> str:
        counter["n"] += 1
        filename = name or f"doc_{counter['n']}.pdf"
        path = tmp_path / filename
        _make_pdf(path, page_count=page_count, label=label)
        return str(path)

    return _factory


@pytest.fixture
def template_with_bookmarks(tmp_path) -> str:
    """Plantilla sintetica de 7 paginas equivalente al caso de referencia:

    0: portada
    1: indice
    2: "1. CONCILIACION DE MATERIALES"
    3: "1.1 DIAGRAMAS MECANICOS"
    4: "1.2 PULL & RUN BES"
    5: "2. CERTIFICADOS DE CALIDAD"
    6: "3. ANEXOS"
    """
    path = tmp_path / "plantilla.pdf"
    doc = fitz.open()
    labels = [
        "PORTADA",
        "INDICE",
        "1. CONCILIACION DE MATERIALES",
        "1.1 DIAGRAMAS MECANICOS",
        "1.2 PULL & RUN BES",
        "2. CERTIFICADOS DE CALIDAD",
        "3. ANEXOS",
    ]
    for label in labels:
        page = doc.new_page(width=595, height=842)
        page.insert_text((40, 60), label, fontsize=14)

    toc = [
        [1, "1. CONCILIACION DE MATERIALES", 3],
        [2, "1.1 DIAGRAMAS MECANICOS", 4],
        [2, "1.2 PULL & RUN BES", 5],
        [1, "2. CERTIFICADOS DE CALIDAD", 6],
        [1, "3. ANEXOS", 7],
    ]
    doc.set_toc(toc)
    doc.save(str(path))
    doc.close()
    return str(path)
