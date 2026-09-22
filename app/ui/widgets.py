"""Widgets reutilizables de la interfaz principal."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QKeyEvent
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


def _pdf_paths_from_mime(mime_data) -> list[str]:
    """Extrae las rutas locales de archivos .pdf de un evento de drag&drop
    originado fuera de la aplicacion (por ejemplo, el Explorador de Windows).
    """
    if not mime_data.hasUrls():
        return []
    paths = []
    for url in mime_data.urls():
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if path.lower().endswith(".pdf"):
            paths.append(path)
    return paths


class DocumentListWidget(QListWidget):
    """Lista de documentos de una seccion, reordenable por arrastre.

    Ademas de reordenar internamente (arrastrar un item a otra posicion de
    la misma lista), acepta que se arrastren archivos PDF desde fuera de la
    aplicacion (por ejemplo, el Explorador de Windows) y los suelten aqui
    para agregarlos a la seccion actual.
    """

    order_changed = Signal()
    files_dropped = Signal(list)  # list[str]: rutas .pdf soltadas desde fuera
    delete_requested = Signal()  # tecla Supr/Backspace con documento(s) seleccionados

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setAlternatingRowColors(True)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - nombre Qt
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selectedItems():
            self.delete_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - nombre Qt
        if _pdf_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802 - nombre Qt
        if _pdf_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - nombre Qt
        paths = _pdf_paths_from_mime(event.mimeData())
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)
            return
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
    """Arbol de secciones/subsecciones del dossier.

    Tambien acepta arrastrar archivos PDF directamente sobre una seccion
    del arbol (sin necesidad de seleccionarla primero) para agregarlos ahi.
    """

    section_selected = Signal(str)
    files_dropped_on_section = Signal(str, list)  # section_id, list[str]
    delete_requested = Signal()  # tecla Supr/Backspace con una seccion seleccionada

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(["Seccion", "Documentos"])
        self.setColumnWidth(0, 320)
        self.itemSelectionChanged.connect(self._on_selection_changed)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - nombre Qt
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selectedItems():
            self.delete_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

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

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - nombre Qt
        if _pdf_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802 - nombre Qt
        if _pdf_paths_from_mime(event.mimeData()):
            item = self.itemAt(event.position().toPoint())
            if item is not None:
                event.acceptProposedAction()
                return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - nombre Qt
        paths = _pdf_paths_from_mime(event.mimeData())
        if paths:
            item = self.itemAt(event.position().toPoint())
            if item is not None:
                section_id = item.data(0, Qt.UserRole)
                event.acceptProposedAction()
                self.files_dropped_on_section.emit(section_id, paths)
                return
        super().dropEvent(event)
