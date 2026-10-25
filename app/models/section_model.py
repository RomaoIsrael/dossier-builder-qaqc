"""Modelo de datos para una seccion (o subseccion) del dossier."""
from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from app.models.document_model import DocumentItem


def _normalize_text(text: str) -> str:
    """Quita tildes y pasa a minusculas, para comparar titulos sin
    depender de como el usuario escribio los acentos."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").lower()


def looks_like_tuberia_section(title: str) -> bool:
    """Publica (sin guion bajo): la usan tanto ``SectionNode.from_dict``
    (proyectos existentes) como ``bookmark_manager`` (proyectos nuevos
    creados desde una plantilla) para decidir el valor por defecto de
    ``always_backup_originals``."""
    return "tuberia" in _normalize_text(title)


@dataclass
class SectionNode:
    """Nodo del arbol de secciones del dossier.

    Un nodo puede representar una seccion de la plantilla (con una pagina
    separadora fisica dentro del PDF de plantilla, ``template_page_index``)
    o una subseccion dinamica creada por el usuario (por ejemplo, dentro de
    ANEXOS), que no tiene pagina separadora propia en la plantilla.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    numbering: str = ""  # "1", "1.1", "3.2", etc. Puede quedar vacio en subsecciones dinamicas.
    level: int = 1  # 1 = seccion principal, 2 = subseccion, 3 = sub-subseccion...
    order: int = 0

    # Indice de pagina (0-based) de la pagina separadora dentro del PDF de
    # plantilla original. None si la seccion es dinamica (no existe en la
    # plantilla) o si aun no se ha asociado a una pagina.
    template_page_index: Optional[int] = None

    is_dynamic: bool = False
    create_bookmark: bool = True

    # Si esta activo, TODOS los documentos de esta seccion se copian a
    # 00_ORIGINALES_FIRMADOS/ con el prefijo "pag N_" al generar el dossier,
    # sin importar si tienen firma o el tratamiento elegido (a diferencia del
    # comportamiento normal, que solo respalda documentos con firma). Pensado
    # para secciones como TUBERIA, donde se quiere trazabilidad de pagina de
    # todos los documentos, no solo de los firmados. Se puede activar o
    # desactivar con el menu de clic derecho sobre la seccion.
    always_backup_originals: bool = False

    documents: list[DocumentItem] = field(default_factory=list)
    children: list["SectionNode"] = field(default_factory=list)

    parent_id: Optional[str] = None

    def iter_all_sections(self):
        """Recorre este nodo y todos sus descendientes (pre-orden)."""
        yield self
        for child in self.children:
            yield from child.iter_all_sections()

    def find(self, section_id: str) -> Optional["SectionNode"]:
        for node in self.iter_all_sections():
            if node.id == section_id:
                return node
        return None

    def total_documents(self) -> int:
        return sum(len(node.documents) for node in self.iter_all_sections())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "numbering": self.numbering,
            "level": self.level,
            "order": self.order,
            "template_page_index": self.template_page_index,
            "is_dynamic": self.is_dynamic,
            "create_bookmark": self.create_bookmark,
            "always_backup_originals": self.always_backup_originals,
            "parent_id": self.parent_id,
            "documents": [d.to_dict() for d in self.documents],
            "children": [c.to_dict() for c in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SectionNode":
        title = data.get("title", "")
        always_backup_originals = data.get("always_backup_originals")
        if always_backup_originals is None:
            # Proyectos guardados antes de que existiera este campo: se
            # activa por defecto para secciones de Tuberia (comportamiento
            # pedido explicitamente), el resto queda en False como siempre.
            always_backup_originals = looks_like_tuberia_section(title)
        node = cls(
            id=data.get("id", str(uuid.uuid4())),
            title=title,
            numbering=data.get("numbering", ""),
            level=data.get("level", 1),
            order=data.get("order", 0),
            template_page_index=data.get("template_page_index"),
            is_dynamic=data.get("is_dynamic", False),
            create_bookmark=data.get("create_bookmark", True),
            always_backup_originals=bool(always_backup_originals),
            parent_id=data.get("parent_id"),
        )
        node.documents = [DocumentItem.from_dict(d) for d in data.get("documents", [])]
        node.children = [SectionNode.from_dict(c) for c in data.get("children", [])]
        return node
