"""Genera un proyecto de ejemplo end-to-end (sin usar documentos reales).

Crea, dentro de examples/example_project/:
  - plantilla.pdf         (plantilla sintetica con portada, indice, separadores y bookmarks)
  - input_docs/*.pdf      (documentos de entrada "falsos", solo para demostrar el flujo)
  - proyecto_ejemplo.dossierproj  (proyecto ya armado, listo para abrir en la app)

Uso:
    python examples/build_example_project.py

Luego, desde la aplicacion: Abrir proyecto -> examples/example_project/proyecto_ejemplo.dossierproj
y presionar "Generar dossier" para ver el flujo completo.

No se incluyen documentos reales del dossier de referencia del cliente: todo
el contenido aqui es sintetico, generado por este mismo script, para no
distribuir informacion corporativa/confidencial.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fitz  # noqa: E402

from app.core import pdf_engine  # noqa: E402
from app.core.bookmark_manager import build_section_tree_from_toc  # noqa: E402
from app.core.project import ProjectService  # noqa: E402
from app.models.document_model import DocumentItem  # noqa: E402
from app.models.project_model import Project  # noqa: E402
from app.models.section_model import SectionNode  # noqa: E402

EXAMPLE_DIR = Path(__file__).resolve().parent / "example_project"
DOCS_DIR = EXAMPLE_DIR / "input_docs"


def _make_pdf(path: Path, page_count: int, label: str, width=595, height=842) -> None:
    doc = fitz.open()
    for i in range(page_count):
        page = doc.new_page(width=width, height=height)
        page.insert_text((50, 60), f"{label}", fontsize=16)
        page.insert_text((50, 90), f"Pagina {i + 1} de {page_count}", fontsize=11)
    doc.save(str(path))
    doc.close()


def build_template(path: Path) -> None:
    labels = [
        "DOSSIER DE CALIDAD - EJEMPLO",
        "CONTENIDO / INDICE",
        "1. CONCILIACION DE MATERIALES",
        "1.1 DIAGRAMAS MECANICOS",
        "1.2 PULL & RUN BES",
        "1.3 GUIAS DE REMISION TUBERIA",
        "1.4 GUIAS DE REMISION HERRAMIENTAS",
        "1.5 GUIAS DE REMISION EQUIPO BES",
        "2. CERTIFICADOS DE CALIDAD",
        "2.1 CABEZAL",
        "2.2 TUBERIA",
        "2.3 HERRAMIENTAS",
        "2.4 EQUIPO BES",
        "3. ANEXOS",
    ]
    doc = fitz.open()
    for label in labels:
        page = doc.new_page(width=595, height=842)
        page.insert_text((60, 80), label, fontsize=15)

    toc = [
        [1, "1. CONCILIACION DE MATERIALES", 3],
        [2, "1.1 DIAGRAMAS MECANICOS", 4],
        [2, "1.2 PULL & RUN BES", 5],
        [2, "1.3 GUIAS DE REMISION TUBERIA", 6],
        [2, "1.4 GUIAS DE REMISION HERRAMIENTAS", 7],
        [2, "1.5 GUIAS DE REMISION EQUIPO BES", 8],
        [1, "2. CERTIFICADOS DE CALIDAD", 9],
        [2, "2.1 CABEZAL", 10],
        [2, "2.2 TUBERIA", 11],
        [2, "2.3 HERRAMIENTAS", 12],
        [2, "2.4 EQUIPO BES", 13],
        [1, "3. ANEXOS", 14],
    ]
    doc.set_toc(toc)
    doc.save(str(path))
    doc.close()


def _find(sections: list[SectionNode], numbering: str) -> SectionNode | None:
    for s in sections:
        if s.numbering == numbering:
            return s
        found = _find(s.children, numbering)
        if found:
            return found
    return None


def main() -> None:
    EXAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    template_path = EXAMPLE_DIR / "plantilla.pdf"
    build_template(template_path)

    toc = pdf_engine.extract_toc(str(template_path))
    sections = build_section_tree_from_toc(toc)

    project = Project(name="Proyecto de ejemplo")
    project.template_path = str(template_path)
    project.template_page_count = pdf_engine.get_page_count(str(template_path))
    project.sections = sections
    project.metadata.proyecto = "Ejemplo"
    project.metadata.pozo = "POZO-DEMO-1"
    project.metadata.wo = "WO-0001"
    project.metadata.codigo = "DEMO-0001"
    project.metadata.contrato = "CONTRATO-DEMO"
    project.metadata.bloque = "BLOQUE-DEMO"
    project.metadata.revision = "0"
    project.metadata.tipo = "QA"

    sample_docs = {
        "1.1": [("Diagrama_Inicial.pdf", 2), ("Diagrama_Final_Firmado.pdf", 2)],
        "1.2": [("Pull_Report.pdf", 3), ("Run_Report.pdf", 2)],
        "2.1": [("Certificado_Cabezal.pdf", 1)],
        "2.2": [("Certificado_Tuberia.pdf", 2)],
    }

    for numbering, files in sample_docs.items():
        section = _find(sections, numbering)
        if section is None:
            continue
        for filename, pages in files:
            file_path = DOCS_DIR / filename
            _make_pdf(file_path, pages, filename)
            doc_item = DocumentItem(source_path=str(file_path), order=len(section.documents))
            if "Firmado" in filename:
                # Simula un documento marcado manualmente para aplanar (en un
                # caso real, la deteccion automatica de firma lo marcaria solo).
                from app.models.document_model import SignatureTreatment

                doc_item.signature_treatment = SignatureTreatment.FLATTEN
                doc_item.has_signature = True
            section.documents.append(doc_item)

    anexos = _find(sections, "3")
    if anexos is not None:
        habilitante = DOCS_DIR / "Documento_Habilitante.pdf"
        _make_pdf(habilitante, 1, "Documento_Habilitante.pdf")
        anexos.documents.append(DocumentItem(source_path=str(habilitante), order=len(anexos.documents)))

        reportes = SectionNode(
            title="REPORTES FOTOGRAFICOS",
            level=anexos.level + 1,
            order=len(anexos.children),
            template_page_index=None,
            is_dynamic=True,
            parent_id=anexos.id,
        )
        foto_path = DOCS_DIR / "Reporte_Fotografico.pdf"
        _make_pdf(foto_path, 2, "Reporte_Fotografico.pdf")
        reportes.documents.append(DocumentItem(source_path=str(foto_path)))
        anexos.children.append(reportes)

    service = ProjectService()
    saved_path = service.save(project, str(EXAMPLE_DIR / "proyecto_ejemplo"))
    print(f"Proyecto de ejemplo creado en: {saved_path}")
    print("Abralo desde la aplicacion (Abrir proyecto) o genere el dossier directamente con:")
    print("  from app.core.dossier_builder import DossierBuilder")


if __name__ == "__main__":
    main()
