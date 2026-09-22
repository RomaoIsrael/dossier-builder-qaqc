"""Dialogos secundarios: metadatos, configuracion, resultados de validacion,
nueva subseccion y vista previa de PDF.
"""
from __future__ import annotations

from typing import Optional

import fitz  # PyMuPDF
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from app.core.validator import Severity, ValidationReport
from app.models.project_model import ProjectMetadata, ProjectSettings


class MetadataDialog(QDialog):
    """Edicion de los campos de encabezado del proyecto (Pozo, WO, Codigo, etc.)."""

    def __init__(self, metadata: ProjectMetadata, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metadatos del proyecto")
        self.setMinimumWidth(420)

        self._fields: dict[str, QLineEdit] = {}
        form = QFormLayout()
        labels = {
            "proyecto": "Proyecto",
            "pozo": "Pozo",
            "wo": "WO",
            "codigo": "Codigo",
            "contrato": "Contrato",
            "bloque": "Bloque",
            "fecha": "Fecha",
            "revision": "Revision",
            "tipo": "Tipo",
            "titulo_pdf": "Titulo (PDF)",
            "autor_pdf": "Autor (PDF)",
            "asunto_pdf": "Asunto (PDF)",
            "keywords_pdf": "Palabras clave (PDF)",
        }
        for field_name, label in labels.items():
            edit = QLineEdit(getattr(metadata, field_name, ""))
            self._fields[field_name] = edit
            form.addRow(label, edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def result_metadata(self) -> ProjectMetadata:
        data = {name: edit.text() for name, edit in self._fields.items()}
        return ProjectMetadata(**data)


class SettingsDialog(QDialog):
    """Configuracion de procesamiento del proyecto (DPI, firmas, salida, nombre)."""

    def __init__(self, settings: ProjectSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuracion del proyecto")
        self.setMinimumWidth(420)

        form = QFormLayout()

        self.dpi_combo = QComboBox()
        self.dpi_combo.addItems(["150", "200", "300", "400"])
        self.dpi_combo.setCurrentText(str(settings.flatten_dpi))
        form.addRow("DPI de aplanado", self.dpi_combo)

        self.format_combo = QComboBox()
        self.format_combo.addItems(["jpeg", "png"])
        self.format_combo.setCurrentText(settings.flatten_image_format)
        form.addRow("Formato de imagen", self.format_combo)

        self.signature_mode_combo = QComboBox()
        self.signature_mode_combo.addItem("Automatico (detectar firmas)", "auto")
        self.signature_mode_combo.addItem("Preguntar siempre", "ask")
        self.signature_mode_combo.addItem("Nunca aplanar", "never")
        index = self.signature_mode_combo.findData(settings.signature_mode)
        self.signature_mode_combo.setCurrentIndex(max(0, index))
        form.addRow("Tratamiento de firmas", self.signature_mode_combo)

        self.naming_edit = QLineEdit(settings.output_naming_pattern)
        form.addRow("Patron de nombre de salida", self.naming_edit)

        self.output_dir_edit = QLineEdit(settings.output_dir)
        form.addRow("Carpeta de salida por defecto", self.output_dir_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("Variables disponibles: {codigo} {pozo} {wo} {tipo} {revision} {contrato} {bloque}"))
        layout.addWidget(buttons)

    def apply_to(self, settings: ProjectSettings) -> ProjectSettings:
        settings.flatten_dpi = int(self.dpi_combo.currentText())
        settings.flatten_image_format = self.format_combo.currentText()
        settings.signature_mode = self.signature_mode_combo.currentData()
        settings.output_naming_pattern = self.naming_edit.text() or settings.output_naming_pattern
        settings.output_dir = self.output_dir_edit.text()
        return settings


_SEVERITY_PREFIX = {Severity.OK: "OK", Severity.WARNING: "ADVERTENCIA", Severity.ERROR: "ERROR"}
_SEVERITY_COLOR = {Severity.OK: Qt.darkGreen, Severity.WARNING: Qt.darkYellow, Severity.ERROR: Qt.red}


class ValidationResultsDialog(QDialog):
    """Muestra el resultado de 'Validar dossier': OK / Advertencia / Error por item."""

    def __init__(self, report: ValidationReport, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Resultado de validacion")
        self.resize(620, 480)

        layout = QVBoxLayout(self)

        summary = QLabel(
            f"{len(report.messages)} verificaciones - "
            f"{len(report.warnings)} advertencia(s) - {len(report.errors)} error(es)"
        )
        layout.addWidget(summary)

        listbox = QListWidget()
        for msg in report.messages:
            prefix = _SEVERITY_PREFIX[msg.severity]
            item = QListWidgetItem(f"[{prefix}] {msg.message}")
            item.setForeground(_SEVERITY_COLOR[msg.severity])
            listbox.addItem(item)
        layout.addWidget(listbox)

        if report.can_generate:
            footer = QLabel("Se puede generar el dossier (no hay errores criticos).")
        else:
            footer = QLabel("No se puede generar el dossier: corrija los errores marcados arriba.")
            footer.setStyleSheet("color: red; font-weight: bold;")
        layout.addWidget(footer)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class NewSectionDialog(QDialog):
    """Pide el nombre de una nueva (sub)seccion dinamica."""

    def __init__(self, parent=None, default_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Nueva subseccion")
        self.setMinimumWidth(360)

        self.name_edit = QLineEdit(default_name)

        form = QFormLayout()
        form.addRow("Nombre de la subseccion", self.name_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def section_name(self) -> str:
        return self.name_edit.text().strip()


class PdfPreviewDialog(QDialog):
    """Vista previa simple de un PDF: navegacion de paginas y zoom."""

    def __init__(self, pdf_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Vista previa - {pdf_path}")
        self.resize(720, 860)

        self._path = pdf_path
        self._doc: Optional[fitz.Document] = None
        self._page_index = 0
        self._zoom = 1.2

        self.image_label = QLabel("Cargando...")
        self.image_label.setAlignment(Qt.AlignCenter)

        self.page_label = QLabel("")

        prev_btn = QPushButton("< Anterior")
        next_btn = QPushButton("Siguiente >")
        zoom_in_btn = QPushButton("Zoom +")
        zoom_out_btn = QPushButton("Zoom -")
        prev_btn.clicked.connect(self._prev_page)
        next_btn.clicked.connect(self._next_page)
        zoom_in_btn.clicked.connect(self._zoom_in)
        zoom_out_btn.clicked.connect(self._zoom_out)

        nav = QHBoxLayout()
        nav.addWidget(prev_btn)
        nav.addWidget(self.page_label)
        nav.addWidget(next_btn)
        nav.addStretch()
        nav.addWidget(zoom_out_btn)
        nav.addWidget(zoom_in_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(nav)
        layout.addWidget(self.image_label, stretch=1)

        self._open_and_render()

    def _open_and_render(self) -> None:
        try:
            self._doc = fitz.open(self._path)
        except Exception as exc:  # noqa: BLE001
            self.image_label.setText(f"No se pudo abrir el PDF:\n{exc}")
            return
        self._render_current_page()

    def _render_current_page(self) -> None:
        if not self._doc:
            return
        page = self._doc[self._page_index]
        matrix = fitz.Matrix(self._zoom, self._zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
        self.image_label.setPixmap(QPixmap.fromImage(image))
        self.page_label.setText(f"Pagina {self._page_index + 1} / {self._doc.page_count}")

    def _prev_page(self) -> None:
        if self._doc and self._page_index > 0:
            self._page_index -= 1
            self._render_current_page()

    def _next_page(self) -> None:
        if self._doc and self._page_index < self._doc.page_count - 1:
            self._page_index += 1
            self._render_current_page()

    def _zoom_in(self) -> None:
        self._zoom = min(4.0, self._zoom + 0.2)
        self._render_current_page()

    def _zoom_out(self) -> None:
        self._zoom = max(0.4, self._zoom - 0.2)
        self._render_current_page()

    def closeEvent(self, event) -> None:  # noqa: N802 - nombre Qt
        if self._doc:
            self._doc.close()
        super().closeEvent(event)
