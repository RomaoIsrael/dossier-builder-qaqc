import json

import fitz
import pytest

from app.core import pdf_engine
from app.core.bookmark_manager import build_section_tree_from_toc
from app.core.dossier_builder import (
    CancelledError,
    DossierBuilder,
    DossierGenerationError,
    _estimate_index_page_count,
    _render_index_document,
)
from app.models.document_model import DocumentItem
from app.models.project_model import Project
from app.models.section_model import SectionNode


def _find(sections, numbering):
    for s in sections:
        if s.numbering == numbering:
            return s
        found = _find(s.children, numbering)
        if found:
            return found
    return None


@pytest.fixture
def populated_project(template_with_bookmarks, make_pdf):
    toc = pdf_engine.extract_toc(template_with_bookmarks)
    sections = build_section_tree_from_toc(toc)

    project = Project(name="Proyecto integracion", template_path=template_with_bookmarks)
    project.sections = sections
    project.metadata.codigo = "61G2158"
    project.metadata.pozo = "PZ1"
    project.metadata.tipo = "QA"
    project.metadata.revision = "0"
    project.settings.output_naming_pattern = "{codigo}-{pozo}-{tipo}-{revision}"

    sec_1_1 = _find(sections, "1.1")
    sec_1_1.documents.append(DocumentItem(source_path=make_pdf(page_count=2, label="1.1a")))
    sec_1_1.documents.append(DocumentItem(source_path=make_pdf(page_count=2, label="1.1b")))

    sec_1_2 = _find(sections, "1.2")
    sec_1_2.documents.append(DocumentItem(source_path=make_pdf(page_count=3, label="1.2a")))

    sec_anexos = _find(sections, "3")
    sec_anexos.documents.append(DocumentItem(source_path=make_pdf(page_count=1, label="anexo_directo")))

    dyn = SectionNode(
        title="REPORTES FOTOGRAFICOS",
        level=sec_anexos.level + 1,
        order=len(sec_anexos.children),
        template_page_index=None,
        is_dynamic=True,
        parent_id=sec_anexos.id,
    )
    dyn.documents.append(DocumentItem(source_path=make_pdf(page_count=2, label="reportes")))
    sec_anexos.children.append(dyn)

    return project, dyn


def test_generate_produces_expected_total_pages(populated_project, tmp_path):
    project, dyn = populated_project
    builder = DossierBuilder(project)

    result = builder.generate(str(tmp_path))

    # 7 paginas de plantilla + 2+2 (1.1) + 3 (1.2) + 1 (anexo directo) + 2 (dinamica)
    assert result.total_pages == 17
    assert result.total_documents == 5
    assert result.flattened_count == 0


def test_generate_bookmarks_point_to_correct_pages(populated_project, tmp_path):
    project, dyn = populated_project
    builder = DossierBuilder(project)
    result = builder.generate(str(tmp_path))

    out_doc = fitz.open(result.output_pdf_path)
    try:
        toc = out_doc.get_toc(simple=True)
    finally:
        out_doc.close()

    toc_by_title = {title: page for _, title, page in toc}

    assert toc_by_title["1 CONCILIACION DE MATERIALES"] == 3
    assert toc_by_title["1.1 DIAGRAMAS MECANICOS"] == 4
    assert toc_by_title["1.2 PULL & RUN BES"] == 9
    assert toc_by_title["2 CERTIFICADOS DE CALIDAD"] == 13
    assert toc_by_title["3 ANEXOS"] == 14
    assert toc_by_title["REPORTES FOTOGRAFICOS"] == 16


def test_generate_creates_expected_folder_structure(populated_project, tmp_path):
    project, dyn = populated_project
    builder = DossierBuilder(project)
    result = builder.generate(str(tmp_path))

    root = tmp_path / "Proyecto integracion"
    assert (root / "02_DOSSIER_FINAL").exists()
    assert (root / "03_REPORTES" / "manifest.json").exists()
    assert (root / "03_REPORTES" / "Reporte_Generacion.pdf").exists()

    manifest = json.loads((root / "03_REPORTES" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["total_documents"] == 5
    assert manifest["output_pdf"]["sha256"] == result.sha256_final


def test_generate_uses_naming_pattern_for_output_filename(populated_project, tmp_path):
    project, dyn = populated_project
    builder = DossierBuilder(project)
    result = builder.generate(str(tmp_path))
    assert result.output_pdf_path.endswith("61G2158-PZ1-QA-0.pdf")


def test_generate_blocks_when_validation_has_errors(tmp_path):
    project = Project(name="Sin plantilla")
    builder = DossierBuilder(project)
    with pytest.raises(DossierGenerationError):
        builder.generate(str(tmp_path))


def test_generate_can_be_cancelled(populated_project, tmp_path):
    project, dyn = populated_project
    builder = DossierBuilder(project)
    with pytest.raises(CancelledError):
        builder.generate(str(tmp_path), cancel_check=lambda: True)


def _populate_page_counts(project):
    """Simula lo que main_window._inspect_document() hace al agregar un
    documento desde la UI: detectar su numero de paginas de antemano."""
    for section in project.iter_all_sections():
        for doc in section.documents:
            doc.page_count = pdf_engine.get_page_count(doc.source_path)


def test_build_preview_outline_matches_real_assembly_positions(populated_project):
    project, dyn = populated_project
    _populate_page_counts(project)
    builder = DossierBuilder(project)

    rows = builder.build_preview_outline()

    doc_rows = [r for r in rows if r.kind == "doc"]
    sec_1_1 = _find(project.sections, "1.1")
    sec_1_2 = _find(project.sections, "1.2")
    sec_3 = _find(project.sections, "3")

    expected_order = [
        sec_1_1.documents[0].id,
        sec_1_1.documents[1].id,
        sec_1_2.documents[0].id,
        sec_3.documents[0].id,
        dyn.documents[0].id,
    ]
    assert [r.document_id for r in doc_rows] == expected_order
    assert [r.start_page for r in doc_rows] == [5, 7, 10, 15, 16]
    assert [r.page_count for r in doc_rows] == [2, 2, 3, 1, 2]

    template_rows = [r for r in rows if r.kind == "template"]
    assert len(template_rows) == 7  # las 7 paginas de la plantilla sintetica
    assert template_rows[0].start_page == 1


def test_build_preview_outline_handles_uninspected_documents(populated_project):
    """Si un documento aun no fue inspeccionado (page_count=None), la vista
    previa no debe fallar: debe asumir 1 pagina como estimacion minima."""
    project, dyn = populated_project
    builder = DossierBuilder(project)  # sin _populate_page_counts

    rows = builder.build_preview_outline()
    doc_rows = [r for r in rows if r.kind == "doc"]
    assert all(r.page_count is None for r in doc_rows)
    assert len(doc_rows) == 5


def test_estimate_index_page_count_fits_on_one_page_for_few_entries():
    assert _estimate_index_page_count(6) == 1
    assert _estimate_index_page_count(0) == 1


def test_estimate_index_page_count_matches_actual_render_for_many_entries():
    entry_count = 120
    estimated = _estimate_index_page_count(entry_count)
    assert estimated > 1

    fake_entries = [(1 if i % 5 == 0 else 2, f"Seccion de prueba {i}", i + 1) for i in range(entry_count)]
    doc = _render_index_document(fake_entries)
    try:
        assert doc.page_count == estimated
    finally:
        doc.close()


def test_generate_with_automatic_index_shifts_bookmarks_and_lists_correct_pages(populated_project, tmp_path):
    project, dyn = populated_project
    project.settings.generate_automatic_index = True
    builder = DossierBuilder(project)

    result = builder.generate(str(tmp_path))

    # 17 paginas del cuerpo (ver test_generate_produces_expected_total_pages)
    # + 1 pagina de indice (6 entradas caben en una sola pagina).
    assert result.total_pages == 18

    out_doc = fitz.open(result.output_pdf_path)
    try:
        toc = out_doc.get_toc(simple=True)
        index_page_text = out_doc[0].get_text()
    finally:
        out_doc.close()

    toc_by_title = {title: page for _, title, page in toc}

    assert toc_by_title["INDICE"] == 1
    # Las mismas posiciones que sin indice (ver test_generate_bookmarks_point_to_correct_pages)
    # pero desplazadas +1 pagina por la pagina de indice insertada al inicio.
    assert toc_by_title["1 CONCILIACION DE MATERIALES"] == 4
    assert toc_by_title["1.1 DIAGRAMAS MECANICOS"] == 5
    assert toc_by_title["1.2 PULL & RUN BES"] == 10
    assert toc_by_title["2 CERTIFICADOS DE CALIDAD"] == 14
    assert toc_by_title["3 ANEXOS"] == 15
    assert toc_by_title["REPORTES FOTOGRAFICOS"] == 17

    # La pagina de indice impresa debe mostrar exactamente esos mismos numeros.
    assert "CONTENIDO" in index_page_text
    assert "1 CONCILIACION DE MATERIALES" in index_page_text
    assert "4" in index_page_text


def test_generate_without_automatic_index_has_no_indice_bookmark(populated_project, tmp_path):
    project, dyn = populated_project
    assert project.settings.generate_automatic_index is False
    builder = DossierBuilder(project)

    result = builder.generate(str(tmp_path))
    assert result.total_pages == 17

    out_doc = fitz.open(result.output_pdf_path)
    try:
        toc_titles = {title for _, title, _ in out_doc.get_toc(simple=True)}
    finally:
        out_doc.close()
    assert "INDICE" not in toc_titles
