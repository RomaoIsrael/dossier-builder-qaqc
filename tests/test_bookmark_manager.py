from app.core import pdf_engine
from app.core.bookmark_manager import (
    build_section_tree_from_toc,
    build_toc_for_document,
    renumber_sections,
)
from app.core.pdf_engine import TocEntry
from app.models.section_model import SectionNode


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


def test_build_section_tree_preserves_unnumbered_root_title():
    """Un bookmark raiz sin numero en el titulo (tipico: "CONTENIDO", la
    matriz/raiz del indice de la plantilla) NUNCA debe recibir un numero
    inventado: debe conservar su titulo tal cual, sin numeracion.
    """
    entries = [
        TocEntry(level=1, title="CONTENIDO", page_index=1),
        TocEntry(level=2, title="1. CONCILIACION DE MATERIALES", page_index=2),
        TocEntry(level=2, title="2. CERTIFICADOS DE CALIDAD", page_index=5),
    ]
    sections = build_section_tree_from_toc(entries)

    assert len(sections) == 1
    root = sections[0]
    assert root.title == "CONTENIDO"
    assert root.numbering == ""

    assert len(root.children) == 2
    assert root.children[0].numbering == "1"
    assert root.children[1].numbering == "2"


def test_build_toc_for_document_keeps_unnumbered_title_without_leading_number():
    entries = [TocEntry(level=1, title="CONTENIDO", page_index=1)]
    sections = build_section_tree_from_toc(entries)
    positions = {sections[0].id: sections[0].template_page_index}

    toc = build_toc_for_document(sections, positions)

    assert toc == [[1, "CONTENIDO", 2]]


def test_renumber_sections_does_not_touch_static_template_sections(template_with_bookmarks):
    """Las secciones que vienen de un bookmark de la plantilla no son
    dinamicas: renumber_sections nunca debe modificar su numeracion, sin
    importar el orden (agregar/eliminar otras secciones no debe correrles
    el numero ni pisarles el titulo original, ej. "CONTENIDO").
    """
    toc = pdf_engine.extract_toc(template_with_bookmarks)
    sections = build_section_tree_from_toc(toc)

    # Simula que el orden interno cambio (por ejemplo al eliminar y volver a
    # cargar secciones); ninguna de estas secciones es dinamica.
    sections[0].order, sections[2].order = sections[2].order, sections[0].order
    renumber_sections(sections)

    by_title = {s.title: s.numbering for s in sections}
    assert by_title["CONCILIACION DE MATERIALES"] == "1"
    assert by_title["CERTIFICADOS DE CALIDAD"] == "2"
    assert by_title["ANEXOS"] == "3"


def test_renumber_sections_numbers_dynamic_children_relative_to_parent(template_with_bookmarks):
    toc = pdf_engine.extract_toc(template_with_bookmarks)
    sections = build_section_tree_from_toc(toc)
    anexos = sections[2]
    assert anexos.title == "ANEXOS"
    assert anexos.numbering == "3"

    dyn1 = SectionNode(
        title="Documento Habilitante", level=anexos.level + 1, order=0, is_dynamic=True, parent_id=anexos.id
    )
    dyn2 = SectionNode(
        title="Acta de Inicio", level=anexos.level + 1, order=1, is_dynamic=True, parent_id=anexos.id
    )
    anexos.children.extend([dyn1, dyn2])

    renumber_sections(sections)

    assert anexos.numbering == "3"  # la seccion de plantilla no se toca
    assert dyn1.numbering == "3.1"
    assert dyn2.numbering == "3.2"


def test_renumber_sections_root_level_dynamic_section():
    dyn_root = SectionNode(title="Seccion nueva", level=1, order=0, is_dynamic=True)
    renumber_sections([dyn_root])
    assert dyn_root.numbering == "1"


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
