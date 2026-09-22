"""Widgets reutilizables de la interfaz principal."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem

from app.models.document_model import DocumentItem, DocumentStatus
from app.models.section_model import SectionNode

STATUS_LABELS = {
    DocumentStatus.PENDING: "",
    DocumentStatus.OK: "",
    DocumentStatus.MISSING: "[FALTANTE]",
    DocumentStatus.CORRUPT: "[DANADO]",
    DocumentStatus.PASSWORD_PROTECTED: "[CON CONTRASENA]",
    DocumentStatus.FLATTENED: "[APLANADO]",
    DocumentStatus.ERROR: "[ERROR]",
}


def document_display_text(doc: DocumentItem, index: int) -> str:
    tags = []
    if doc.has_signature:
        tags.append("FIRMA")
    if doc.will_be_flattened:
        tags.append("SE APLANARA")
    status_tag = STATUS_LABELS.get(doc.status, "")
    if status_tag:
        tags.append(status_tag.strip("[]"))
    suffix = f"  [{' | '.join(tags)}]" if tags else ""
    return f"{index + 1}. {doc.name}{suffix}"


class DocumentListWidget(QListWidget):
    """Lista de documentos de una seccion, reordenable por arrastre."""

    order_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setAlternatingRowColors(True)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - nombre Qt
        super().dropEvent(event)
        self.order_changed.emit()

    def load_documents(self, documents: list[DocumentItem]) -> None:
        self.clear()
        for index, doc in enumerate(documents):
            item = QListWidgetItem(document_display_text(doc, index))
            item.setData(Qt.UserRole, doc.id)
            if doc.status in (
                DocumentStatus.ERROR,
                DocumentStatus.MISSING,
                DocumentStatus.CORRUPT,
                DocumentStatus.PASSWORD_PROTECTED,
            ):
                item.setForeground(Qt.red)
            self.addItem(item)

    def ordered_document_ids(self) -> list[str]:
        return [self.item(i).data(Qt.UserRole) for i in range(self.count())]

    def selected_document_ids(self) -> list[str]:
        return [item.data(Qt.UserRole) for item in self.selectedItems()]


class SectionTreeWidget(QTreeWidget):
    """Arbol de secciones/subsecciones del dossier."""

    section_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(["Seccion", "Documentos"])
        self.setColumnWidth(0, 320)
        self.itemSelectionChanged.connect(self._on_selection_changed)

    def load_sections(self, sections: list[SectionNode]) -> None:
        self.clear()
        for section in sorted(sections, key=lambda s: s.order):
            self._add_node(section, None)
        self.expandAll()

    def _add_node(self, node: SectionNode, parent_item: Optional[QTreeWidgetItem]) -> QTreeWidgetItem:
        label = f"{node.numbering} {node.title}".strip()
        count = str(node.total_documents())
        if parent_item is None:
            item = QTreeWidgetItem(self, [label, count])
        else:
            item = QTreeWidgetItem(parent_item, [label, count])
        item.setData(0, Qt.UserRole, node.id)
        if node.total_documents() == 0 and not node.children:
            item.setForeground(0, Qt.darkYellow)
        for child in sorted(node.children, key=lambda c: c.order):
            self._add_node(child, item)
        return item

    def _on_selection_changed(self) -> None:
        items = self.selectedItems()
        if items:
            self.section_selected.emit(items[0].data(0, Qt.UserRole))

    def select_section(self, section_id: str) -> None:
        iterator_items = self.findItems("", Qt.MatchContains | Qt.MatchRecursive)
        for item in iterator_items:
            if item.data(0, Qt.UserRole) == section_id:
                self.setCurrentItem(item)
                return
