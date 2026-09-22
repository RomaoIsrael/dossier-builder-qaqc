"""Construccion del arbol de secciones a partir de bookmarks, y reconstruccion
de la tabla de contenidos (TOC) del dossier final tras insertar documentos.

Este modulo es deliberadamente "puro" en la parte de calculo (no abre PDFs):
recibe la lista de bookmarks ya extraida por ``pdf_engine.extract_toc`` y
estructuras de datos simples, para poder probarse sin PyMuPDF instalado.
"""
from __future__ import annotations

from app.core.pdf_engine import TocEntry
from app.models.section_model import SectionNode


def build_section_tree_from_toc(entries: list[TocEntry]) -> list[SectionNode]:
    """Construye un arbol de :class:`SectionNode` a partir de bookmarks planos.

    Los ``entries`` deben venir en el orden en que aparecen en el PDF (que es
    como PyMuPDF los devuelve). La jerarquia se infiere del nivel de cada
    bookmark: un nivel N se anida dentro del ultimo bookmark visto de nivel
    N-1 (o inferior).
    """
    roots: list[SectionNode] = []
    stack: list[SectionNode] = []

    for entry in entries:
        level = max(1, entry.level)
        node = SectionNode(
            title=entry.clean_title or entry.title,
            numbering=entry.numbering,
            level=level,
            template_page_index=entry.page_index,
        )

        while stack and stack[-1].level >= level:
            stack.pop()

        if stack:
            parent = stack[-1]
            node.parent_id = parent.id
            node.order = len(parent.children)
            parent.children.append(node)
        else:
            node.order = len(roots)
            roots.append(node)

        stack.append(node)

    fill_missing_numbering(roots)
    return roots


def fill_missing_numbering(nodes: list[SectionNode], parent_numbering: str = "") -> None:
    """Completa la numeracion de nodos que no la traian en el titulo del bookmark."""
    for index, node in enumerate(nodes, start=1):
        if not node.numbering:
            node.numbering = f"{parent_numbering}.{index}" if parent_numbering else str(index)
        fill_missing_numbering(node.children, node.numbering)


def renumber_sections(nodes: list[SectionNode], parent_numbering: str = "") -> None:
    """Recalcula la numeracion de TODOS los nodos segun su orden actual.

    Se usa despues de que el usuario agrega, elimina o reordena secciones
    manualmente en la interfaz.
    """
    for index, node in enumerate(sorted(nodes, key=lambda n: n.order), start=1):
        node.order = index - 1
        node.numbering = f"{parent_numbering}.{index}" if parent_numbering else str(index)
        renumber_sections(node.children, node.numbering)


def build_toc_for_document(
    sections: list[SectionNode],
    section_page_position: dict[str, int],
    document_page_position: dict[str, int] | None = None,
    create_document_bookmarks: bool = False,
) -> list[list]:
    """Construye la lista de TOC (formato PyMuPDF: [nivel, titulo, pagina 1-based]).

    ``section_page_position`` y ``document_page_position`` mapean id de
    seccion/documento a la pagina 0-based que ocupan en el PDF final. Los
    nodos sin posicion conocida (por ejemplo una seccion vacia que nunca se
    materializo) se omiten.
    """
    document_page_position = document_page_position or {}
    toc: list[list] = []

    def walk(nodes: list[SectionNode]) -> None:
        for node in sorted(nodes, key=lambda n: n.order):
            if node.create_bookmark and node.id in section_page_position:
                title = f"{node.numbering} {node.title}".strip() if node.numbering else node.title
                toc.append([node.level, title, section_page_position[node.id] + 1])

                if create_document_bookmarks:
                    for doc in node.documents:
                        if doc.id in document_page_position:
                            toc.append([node.level + 1, doc.name, document_page_position[doc.id] + 1])

            walk(node.children)

    walk(sections)
    return toc
