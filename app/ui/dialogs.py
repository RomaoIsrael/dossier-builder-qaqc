"""Dialogos secundarios: metadatos, configuracion, resultados de validacion,
nueva subseccion y vista previa de PDF.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.dossier_builder import PreviewRow
from app.core.section_suggester import suggest_sections_for_files
from app.core.validator import Severity, ValidationReport
from app.models.project_model import ProjectMetadata, ProjectSettings
from app.models.section_model import SectionNode
from app.services.settings import AppSettings


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

        self.auto_index_checkbox = QCheckBox("Generar indice automatico (seccion/subseccion + pagina)")
        self.auto_index_checkbox.setChecked(settings.generate_automatic_index)
        form.addRow("", self.auto_index_checkbox)

        self.include_docs_checkbox = QCheckBox(
            "Incluir documentos individuales en el indice (nombre + pagina de inicio)"
        )
        self.include_docs_checkbox.setChecked(settings.include_documents_in_index)
        form.addRow("", self.include_docs_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("Variables disponibles: {codigo} {pozo} {wo} {tipo} {revision} {contrato} {bloque}"))
        layout.addWidget(
            QLabel(
                "El indice automatico se inserta al comienzo del dossier final, ademas del indice "
                "existente en la plantilla (que se respeta sin cambios). Con 'Incluir documentos "
                "individuales', cada documento aparece anidado bajo su seccion, ej.:\n"
                "   1.1 DIAGRAMAS MECANICOS ........... 5\n"
                "       Diagrama_Final_Firmado.pdf ..... 7"
            )
        )
        layout.addWidget(buttons)

    def apply_to(self, settings: ProjectSettings) -> ProjectSettings:
        settings.flatten_dpi = int(self.dpi_combo.currentText())
        settings.flatten_image_format = self.format_combo.currentText()
        settings.signature_mode = self.signature_mode_combo.currentData()
        settings.output_naming_pattern = self.naming_edit.text() or settings.output_naming_pattern
        settings.output_dir = self.output_dir_edit.text()
        settings.generate_automatic_index = self.auto_index_checkbox.isChecked()
        settings.include_documents_in_index = self.include_docs_checkbox.isChecked()
        return settings


class PreferencesDialog(QDialog):
    """Preferencias globales de la aplicacion (tema, DPI por defecto, etc.),
    validas para todos los proyectos, no solo el actual.
    """

    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferencias")
        self.setMinimumWidth(420)

        form = QFormLayout()

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Claro", "light")
        self.theme_combo.addItem("Oscuro", "dark")
        index = self.theme_combo.findData(settings.theme)
        self.theme_combo.setCurrentIndex(max(0, index))
        form.addRow("Tema", self.theme_combo)

        self.dpi_combo = QComboBox()
        self.dpi_combo.addItems(["150", "200", "300", "400"])
        self.dpi_combo.setCurrentText(str(settings.default_flatten_dpi))
        form.addRow("DPI de aplanado por defecto", self.dpi_combo)

        self.naming_edit = QLineEdit(settings.default_naming_pattern)
        form.addRow("Patron de nombre por defecto", self.naming_edit)

        self.output_dir_edit = QLineEdit(settings.default_output_dir)
        form.addRow("Carpeta de salida por defecto", self.output_dir_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def apply_to(self, settings: AppSettings) -> AppSettings:
        settings.theme = self.theme_combo.currentData()
        settings.default_flatten_dpi = int(self.dpi_combo.currentText())
        settings.default_naming_pattern = self.naming_edit.text() or settings.default_naming_pattern
        settings.default_output_dir = self.output_dir_edit.text()
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


def _flatten_section_options(sections: list[SectionNode]) -> list[tuple[str, str]]:
    """Devuelve pares (etiqueta, section_id) en el mismo orden que el arbol."""
    options: list[tuple[str, str]] = []
    for root in sections:
        for node in root.iter_all_sections():
            label = f"{node.numbering} {node.title}".strip()
            options.append((label, node.id))
    return options


class AutoDistributeDialog(QDialog):
    """Sugiere, por archivo, la seccion destino segun palabras clave del
    nombre (ver ``app/core/section_suggester.py``), y deja que el usuario
    confirme o corrija cada asignacion antes de agregar los documentos.
    """

    def __init__(self, file_paths: list[str], sections: list[SectionNode], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Distribuir documentos automaticamente")
        self.resize(720, 480)

        self._file_paths = file_paths
        self._section_options = _flatten_section_options(sections)
        suggestions = suggest_sections_for_files([Path(p).name for p in file_paths], sections)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Se sugiere una seccion por archivo segun palabras clave en el nombre. "
                "Revise y corrija antes de confirmar; puede dejar 'No asignar' para omitir un archivo."
            )
        )

        self.table = QTableWidget(len(file_paths), 2)
        self.table.setHorizontalHeaderLabels(["Archivo", "Seccion sugerida"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)

        self._combos: list[QComboBox] = []
        for row, path in enumerate(file_paths):
            name_item = QTableWidgetItem(Path(path).name)
            self.table.setItem(row, 0, name_item)

            combo = QComboBox()
            combo.addItem("(No asignar)", None)
            for label, section_id in self._section_options:
                combo.addItem(label, section_id)

            suggestion = suggestions.get(Path(path).name)
            if suggestion is not None:
                index = combo.findData(suggestion.id)
                if index >= 0:
                    combo.setCurrentIndex(index)

            self.table.setCellWidget(row, 1, combo)
            self._combos.append(combo)

        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_assignments(self) -> dict[str, Optional[str]]:
        return {path: combo.currentData() for path, combo in zip(self._file_paths, self._combos)}


class DossierOutlinePreviewDialog(QDialog):
    """Vista previa estructural del dossier: el orden final de paginas de
    plantilla y documentos, calculado sin abrir ni aplanar ningun PDF (para
    poder revisar el orden incluso en dossiers de cientos de paginas antes
    de generar).
    """

    def __init__(self, rows: list[PreviewRow], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vista previa del dossier (orden estructural)")
        self.resize(760, 560)

        layout = QVBoxLayout(self)

        display_rows = self._collapse_template_runs(rows)
        total_pages = sum(r.page_count or 1 for r in rows)
        layout.addWidget(QLabel(f"{len(rows)} elemento(s) - {total_pages} pagina(s) estimada(s) en total"))

        table = QTableWidget(len(display_rows), 4)
        table.setHorizontalHeaderLabels(["Pagina", "Tipo", "Seccion", "Documento"])
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        for row_index, (page_label, kind_label, section_label, doc_label) in enumerate(display_rows):
            table.setItem(row_index, 0, QTableWidgetItem(page_label))
            table.setItem(row_index, 1, QTableWidgetItem(kind_label))
            table.setItem(row_index, 2, QTableWidgetItem(section_label))
            table.setItem(row_index, 3, QTableWidgetItem(doc_label))

        layout.addWidget(table)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    @staticmethod
    def _collapse_template_runs(rows: list[PreviewRow]) -> list[tuple[str, str, str, str]]:
        """Agrupa paginas de plantilla consecutivas en una sola fila, para
        no listar una por una en plantillas de decenas de paginas.
        """
        display: list[tuple[str, str, str, str]] = []
        i = 0
        while i < len(rows):
            row = rows[i]
            if row.kind == "template":
                start = row.start_page
                j = i
                while j < len(rows) and rows[j].kind == "template":
                    j += 1
                end = rows[j - 1].start_page
                page_label = str(start) if start == end else f"{start}-{end}"
                display.append((page_label, "Plantilla", "", f"{j - i} pagina(s) de plantilla"))
                i = j
            else:
                page_count_label = str(row.page_count) if row.page_count is not None else "?"
                display.append((str(row.start_page), "Documento", row.section_label, f"{row.label} ({page_count_label} pag.)"))
                i += 1
        return display


class DossierThumbnailPreviewDialog(QDialog):
    """Vista previa con miniaturas reales: una imagen por cada pagina de la
    plantilla y por la primera pagina de cada documento, en el orden final
    del dossier. No renderiza el dossier completo pagina por pagina (seria
    demasiado lento en dossiers de cientos de paginas); cada documento se
    representa con su primera pagina, que basta para verificar visualmente
    el orden y que el archivo correcto quedo en cada seccion.
    """

    _THUMB_WIDTH = 120
    _THUMB_HEIGHT = 156
    _COLUMNS = 5

    def __init__(self, rows: list[PreviewRow], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vista previa del dossier (miniaturas)")
        self.resize(820, 680)

        outer_layout = QVBoxLayout(self)
        outer_layout.addWidget(
            QLabel(f"{len(rows)} elemento(s) - se muestra la primera pagina de cada documento")
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(10)

        open_docs: dict[str, Optional[fitz.Document]] = {}

        def get_source_doc(path: str) -> Optional[fitz.Document]:
            if path not in open_docs:
                try:
                    open_docs[path] = fitz.open(path)
                except Exception:  # noqa: BLE001 - un archivo movido/danado no debe romper la vista previa
                    open_docs[path] = None
            return open_docs[path]

        for index, row in enumerate(rows):
            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(2, 2, 2, 2)

            image_label = QLabel()
            image_label.setAlignment(Qt.AlignCenter)
            image_label.setFixedSize(self._THUMB_WIDTH, self._THUMB_HEIGHT)
            image_label.setStyleSheet("border: 1px solid #999999; background-color: white;")

            qpixmap = self._render_thumbnail(row, get_source_doc)
            if qpixmap is not None:
                image_label.setPixmap(
                    qpixmap.scaled(
                        self._THUMB_WIDTH,
                        self._THUMB_HEIGHT,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
            else:
                image_label.setText("(sin vista\nprevia)")

            caption_text = f"pag. {row.start_page}"
            if row.kind == "doc" and row.section_label:
                caption_text += f" - {row.section_label}"
            caption_text += f"\n{row.label}"
            caption = QLabel(caption_text)
            caption.setAlignment(Qt.AlignCenter)
            caption.setWordWrap(True)
            caption.setFixedWidth(self._THUMB_WIDTH)

            cell_layout.addWidget(image_label)
            cell_layout.addWidget(caption)
            grid.addWidget(cell, index // self._COLUMNS, index % self._COLUMNS)

        for doc in open_docs.values():
            if doc is not None:
                doc.close()

        scroll.setWidget(container)
        outer_layout.addWidget(scroll, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        outer_layout.addWidget(buttons)

    def _render_thumbnail(self, row: PreviewRow, get_source_doc) -> Optional[QPixmap]:
        if not row.source_path or not Path(row.source_path).exists():
            return None
        doc = get_source_doc(row.source_path)
        if doc is None or not (0 <= row.source_page_index < doc.page_count):
            return None
        try:
            page = doc[row.source_page_index]
            zoom = self._THUMB_WIDTH / max(page.rect.width, 1.0)
            matrix = fitz.Matrix(zoom, zoom)
            rendered = page.get_pixmap(matrix=matrix, alpha=False)
            image = QImage(rendered.samples, rendered.width, rendered.height, rendered.stride, QImage.Format_RGB888)
            return QPixmap.fromImage(image)
        except Exception:  # noqa: BLE001 - una pagina irrenderizable no debe romper la vista previa
            return None
