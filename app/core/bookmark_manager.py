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

    # Deliberadamente NO se sintetiza numeracion para bookmarks que no la
    # traian en su titulo (por ejemplo "CONTENIDO", que suele ser la raiz
    # del arbol de bookmarks de la plantilla y no un apartado numerado). El
    # objetivo es respetar el indice/bookmarks de la plantilla tal como
    # vienen, sin inventarles nada; ver renumber_sections() para la unica
    # numeracion que SI se calcula (la de secciones creadas por el usuario).
    return roots


def renumber_sections(nodes: list[SectionNode], parent_numbering: str = "") -> None:
    """Recalcula la numeracion de las secciones **dinamicas** (creadas por el
    usuario con "+ Agregar subseccion") segun su orden actual.

    Las secciones que vienen de un bookmark de la plantilla (``is_dynamic``
    False) NUNCA se tocan aqui: conservan siempre su numeracion y titulo
    originales, incluidas las que no tienen numero (como "CONTENIDO", la
    raiz del indice de la plantilla) - inventarles un numero seria alterar
    el indice original, que es justamente lo que no se quiere hacer. Se usa
    despues de que el usuario agrega, elimina o renombra secciones.
    """
    dynamic_index = 0
    for node in sorted(nodes, key=lambda n: n.order):
        if node.is_dynamic:
            dynamic_index += 1
            node.numbering = f"{parent_numbering}.{dynamic_index}" if parent_numbering else str(dynamic_index)
        # Para descender a los hijos se usa la numeracion de ESTE nodo si
        # tiene una (propia de plantilla o recien asignada arriba); si no
        # tiene ninguna (como "CONTENIDO"), se propaga la del padre tal cual.
        effective_numbering = node.numbering or parent_numbering
        renumber_sections(node.children, effective_numbering)


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
