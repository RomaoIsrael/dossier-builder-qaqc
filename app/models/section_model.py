"""Modelo de datos para una seccion (o subseccion) del dossier."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from app.models.document_model import DocumentItem


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
            "parent_id": self.parent_id,
            "documents": [d.to_dict() for d in self.documents],
            "children": [c.to_dict() for c in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SectionNode":
        node = cls(
            id=data.get("id", str(uuid.uuid4())),
            title=data.get("title", ""),
            numbering=data.get("numbering", ""),
            level=data.get("level", 1),
            order=data.get("order", 0),
            template_page_index=data.get("template_page_index"),
            is_dynamic=data.get("is_dynamic", False),
            create_bookmark=data.get("create_bookmark", True),
            parent_id=data.get("parent_id"),
        )
        node.documents = [DocumentItem.from_dict(d) for d in data.get("documents", [])]
        node.children = [SectionNode.from_dict(c) for c in data.get("children", [])]
        return node
