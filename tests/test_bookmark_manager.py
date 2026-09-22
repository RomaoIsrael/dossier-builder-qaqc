from app.core import pdf_engine
from app.core.bookmark_manager import (
    build_section_tree_from_toc,
    build_toc_for_document,
    renumber_sections,
)


def test_build_section_tree_from_toc_infers_hierarchy(template_with_bookmarks):
    toc = pdf_engine.extract_toc(template_with_bookmarks)
    sections = build_section_tree_from_toc(toc)

    assert len(sections) == 3  # "1.", "2.", "3."
    seccion_1 = sections[0]
    assert seccion_1.title == "CONCILIACION DE MATERIALES"
    assert seccion_1.numbering == "1"
    assert seccion_1.template_page_index == 2

    assert len(seccion_1.children) == 2
    sub_1_1, sub_1_2 = seccion_1.children
    assert sub_1_1.numbering == "1.1"
    assert sub_1_1.title == "DIAGRAMAS MECANICOS"
    assert sub_1_1.template_page_index == 3
    assert sub_1_2.numbering == "1.2"
    assert sub_1_2.template_page_index == 4

    assert sections[1].numbering == "2"
    assert sections[2].numbering == "3"
    assert sections[2].title == "ANEXOS"


def test_renumber_sections_after_reorder(template_with_bookmarks):
    toc = pdf_engine.extract_toc(template_with_bookmarks)
    sections = build_section_tree_from_toc(toc)

    # Simula que el usuario reordeno las secciones de nivel 1.
    sections[0].order, sections[2].order = sections[2].order, sections[0].order
    renumber_sections(sections)

    ordered = sorted(sections, key=lambda s: s.order)
    assert [s.numbering for s in ordered] == ["1", "2", "3"]
    # El titulo "ANEXOS" ahora deberia numerarse "1" al haber pasado primero.
    assert ordered[0].title == "ANEXOS"


def test_build_toc_for_document_respects_positions_and_levels(template_with_bookmarks):
    toc = pdf_engine.extract_toc(template_with_bookmarks)
    sections = build_section_tree_from_toc(toc)

    # Simula posiciones finales ya calculadas por el ensamblador.
    positions = {}
    for section in sections:
        positions[section.id] = section.template_page_index
        for child in section.children:
            positions[child.id] = child.template_page_index

    new_toc = build_toc_for_document(sections, positions)

    # Todas las entradas deben estar en formato [nivel, titulo, pagina 1-based]
    assert new_toc[0][0] == 1
    assert new_toc[0][2] == sections[0].template_page_index + 1

    levels = [entry[0] for entry in new_toc]
    assert levels.count(1) == 3
    assert levels.count(2) == 2
