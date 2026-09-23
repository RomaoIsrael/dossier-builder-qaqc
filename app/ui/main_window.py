"""Ventana principal de Dossier Builder QA/QC."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, QThread, QUrl, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QStatusBar,
    QStyle,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app.core import pdf_engine
from app.core.bookmark_manager import build_section_tree_from_toc, renumber_sections
from app.core.dossier_builder import CancelledError, DossierBuilder, DossierGenerationError, GenerationResult
from app.core.project import ProjectError, ProjectService
from app.core.signature_detector import detect_signatures
from app.core.validator import validate_project
from app.models.document_model import DocumentItem, DocumentStatus, SignatureTreatment
from app.models.section_model import SectionNode
from app.services.database import DatabaseService
from app.services.logger import get_logger
from app.services.settings import SettingsService
from app.ui.dialogs import (
    AboutDialog,
    AutoDistributeDialog,
    DossierOutlinePreviewDialog,
    DossierThumbnailPreviewDialog,
    MetadataDialog,
    NewSectionDialog,
    PdfPreviewDialog,
    PreferencesDialog,
    SettingsDialog,
    ValidationResultsDialog,
    flatten_section_options,
)
from app.ui.theme import apply_theme
from app.ui.widgets import DocumentListWidget, SectionTreeWidget
from app.utils.naming import render_naming_pattern

logger = get_logger("ui.main_window")


class GenerationWorker(QThread):
    """Ejecuta DossierBuilder.generate() en un hilo aparte para no congelar la UI."""

    progress = Signal(int, int, str)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, project, output_root: str, output_filename: Optional[str] = None):
        super().__init__()
        self.project = project
        self.output_root = output_root
        self.output_filename = output_filename
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:  # noqa: D102 - metodo estandar de QThread
        builder = DossierBuilder(self.project)
        try:
            result = builder.generate(
                self.output_root,
                output_filename=self.output_filename,
                progress_cb=lambda cur, total, msg: self.progress.emit(cur, total, msg),
                cancel_check=lambda: self._cancelled,
            )
            self.finished_ok.emit(result)
        except CancelledError as exc:
            self.failed.emit(str(exc))
        except DossierGenerationError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - no debe tumbar la aplicacion
            logger.exception("Error inesperado generando el dossier")
            self.failed.emit(f"Error inesperado: {exc}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dossier Builder QA/QC")
        self.resize(1280, 820)

        self.database = DatabaseService()
        self.project_service = ProjectService(database=self.database)
        self.settings_service = SettingsService()

        self.project = None
        self.current_section_id: Optional[str] = None
        self._generation_worker: Optional[GenerationWorker] = None
        self._progress_dialog: Optional[QProgressDialog] = None
        self._dirty = False  # True si hay cambios del proyecto sin guardar

        self._build_toolbar()
        self._build_central_widget()
        self.setStatusBar(QStatusBar())

        self._refresh_ui()

    def _touch_project(self) -> None:
        """Marca el proyecto como modificado (fecha + estado 'sin guardar').

        Se usa en vez de llamar directamente a ``self.project.touch()`` para
        que la ventana sepa, ademas, que hay cambios pendientes y pregunte
        antes de cerrarse si el usuario no los guardo.
        """
        self.project.touch()
        self._dirty = True

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - nombre Qt
        if self.project is not None and self._dirty:
            answer = QMessageBox.question(
                self,
                "Cambios sin guardar",
                "Hay cambios sin guardar en el proyecto actual. Desea guardarlos antes de salir?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if answer == QMessageBox.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.Save:
                self.save_project()
                if self._dirty:
                    # El usuario cancelo el dialogo de guardado (p. ej. "Guardar
                    # como" sin elegir ruta, o un error al escribir el archivo):
                    # no se cierra la aplicacion para no perder los cambios.
                    event.ignore()
                    return
        event.accept()

    # ------------------------------------------------------------------
    # Construccion de la interfaz
    # ------------------------------------------------------------------
    def _build_toolbar(self) -> None:
        # Se usan dos QToolBar en filas separadas (en vez de una sola barra
        # larga) para que quepan todas las acciones sin depender del boton
        # de desborde "»" de Qt, que ademas es dificil de ver en tema oscuro
        # (ver estilo de QToolButton#qt_toolbar_ext_button en theme.py).
        toolbar_top = QToolBar("Proyecto")
        toolbar_top.setObjectName("toolbarProyecto")
        toolbar_top.setMovable(False)
        toolbar_top.setFloatable(False)
        toolbar_top.setIconSize(QSize(18, 18))
        toolbar_top.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar_top)
        self.addToolBarBreak()

        toolbar_bottom = QToolBar("Dossier")
        toolbar_bottom.setObjectName("toolbarDossier")
        toolbar_bottom.setMovable(False)
        toolbar_bottom.setFloatable(False)
        toolbar_bottom.setIconSize(QSize(18, 18))
        toolbar_bottom.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar_bottom)

        style = self.style()

        def add_action(toolbar: QToolBar, text: str, handler, icon: Optional[QStyle.StandardPixmap] = None) -> QAction:
            action = QAction(text, self)
            if icon is not None:
                action.setIcon(style.standardIcon(icon))
            action.triggered.connect(handler)
            toolbar.addAction(action)
            return action

        # Fila 1: gestion del proyecto (archivo, metadatos, configuracion).
        add_action(toolbar_top, "Nuevo proyecto", self.new_project, QStyle.SP_FileIcon)
        add_action(toolbar_top, "Abrir proyecto", self.open_project, QStyle.SP_DialogOpenButton)
        add_action(toolbar_top, "Guardar", self.save_project, QStyle.SP_DialogSaveButton)
        add_action(toolbar_top, "Guardar como...", self.save_project_as, QStyle.SP_DriveFDIcon)
        toolbar_top.addSeparator()
        add_action(toolbar_top, "Metadatos", self.edit_metadata, QStyle.SP_FileDialogInfoView)
        add_action(toolbar_top, "Configuracion", self.edit_settings, QStyle.SP_FileDialogDetailedView)
        add_action(toolbar_top, "Preferencias", self.edit_preferences, QStyle.SP_ComputerIcon)
        toolbar_top.addSeparator()
        add_action(toolbar_top, "Acerca de", self.show_about_dialog, QStyle.SP_MessageBoxInformation)

        # Fila 2: flujo de trabajo del dossier (distribuir, revisar, generar).
        add_action(toolbar_bottom, "Distribuir documentos (auto)", self.auto_distribute_documents, QStyle.SP_FileDialogListView)
        add_action(toolbar_bottom, "Vista previa del dossier", self.preview_dossier_outline, QStyle.SP_FileDialogContentsView)
        add_action(toolbar_bottom, "Vista previa con miniaturas", self.preview_dossier_thumbnails, QStyle.SP_DirIcon)
        toolbar_bottom.addSeparator()
        add_action(toolbar_bottom, "Validar dossier", self.validate_dossier, QStyle.SP_DialogApplyButton)
        self.generate_action = add_action(toolbar_bottom, "Generar dossier", self.generate_dossier, QStyle.SP_MediaPlay)

    def _build_central_widget(self) -> None:
        splitter = QSplitter(Qt.Horizontal)

        # -- Panel izquierdo: arbol de secciones ---------------------------
        self.tree = SectionTreeWidget()
        self.tree.section_selected.connect(self._on_section_selected)
        self.tree.files_dropped_on_section.connect(self._on_files_dropped_on_section)
        self.tree.customContextMenuRequested.connect(self._show_section_context_menu)
        self.tree.delete_requested.connect(self.remove_section)
        splitter.addWidget(self.tree)

        # -- Panel central: documentos de la seccion seleccionada -----------
        center = QWidget()
        center_layout = QVBoxLayout(center)

        self.section_label = QLabel("Seleccione una seccion")
        self.section_label.setStyleSheet("font-weight: 600; font-size: 13pt; padding: 4px 2px;")
        center_layout.addWidget(self.section_label)

        self.doc_list = DocumentListWidget()
        self.doc_list.order_changed.connect(self._on_documents_reordered)
        self.doc_list.itemDoubleClicked.connect(lambda _item: self.preview_selected_document())
        self.doc_list.files_dropped.connect(self._on_files_dropped_on_document_list)
        self.doc_list.customContextMenuRequested.connect(self._show_document_context_menu)
        self.doc_list.delete_requested.connect(self.remove_selected_documents)
        center_layout.addWidget(self.doc_list, stretch=1)

        buttons_row1 = QHBoxLayout()
        self.btn_add_docs = QPushButton("+ Agregar documento(s)")
        self.btn_add_docs.clicked.connect(self.add_documents)
        self.btn_add_folder = QPushButton("+ Agregar carpeta")
        self.btn_add_folder.clicked.connect(self.add_documents_from_folder)
        self.btn_add_subsection = QPushButton("+ Agregar subseccion")
        self.btn_add_subsection.clicked.connect(self.add_subsection)
        self.btn_remove_section = QPushButton("Eliminar seccion")
        self.btn_remove_section.clicked.connect(self.remove_section)
        buttons_row1.addWidget(self.btn_add_docs)
        buttons_row1.addWidget(self.btn_add_folder)
        buttons_row1.addWidget(self.btn_add_subsection)
        buttons_row1.addWidget(self.btn_remove_section)
        center_layout.addLayout(buttons_row1)

        buttons_row2 = QHBoxLayout()
        self.btn_move_up = QPushButton("Subir")
        self.btn_move_up.clicked.connect(lambda: self._move_selected(-1))
        self.btn_move_down = QPushButton("Bajar")
        self.btn_move_down.clicked.connect(lambda: self._move_selected(1))
        self.btn_remove = QPushButton("Eliminar")
        self.btn_remove.clicked.connect(self.remove_selected_documents)
        self.btn_preview = QPushButton("Vista previa")
        self.btn_preview.clicked.connect(self.preview_selected_document)
        self.btn_treatment = QPushButton("Tratamiento de firma...")
        self.btn_treatment.clicked.connect(self._show_treatment_menu)
        buttons_row2.addWidget(self.btn_move_up)
        buttons_row2.addWidget(self.btn_move_down)
        buttons_row2.addWidget(self.btn_remove)
        buttons_row2.addWidget(self.btn_preview)
        buttons_row2.addWidget(self.btn_treatment)
        center_layout.addLayout(buttons_row2)

        buttons_row3 = QHBoxLayout()
        self.btn_open_external = QPushButton("Abrir documento")
        self.btn_open_external.clicked.connect(self.open_selected_document_external)
        self.btn_open_folder = QPushButton("Abrir ubicacion")
        self.btn_open_folder.clicked.connect(self.open_selected_document_folder)
        buttons_row3.addWidget(self.btn_open_external)
        buttons_row3.addWidget(self.btn_open_folder)
        center_layout.addLayout(buttons_row3)

        splitter.addWidget(center)
        splitter.setSizes([380, 900])

        self.setCentralWidget(splitter)

    # ------------------------------------------------------------------
    # Gestion de proyectos
    # ------------------------------------------------------------------
    def new_project(self) -> None:
        name, ok = QInputDialog.getText(self, "Nuevo proyecto", "Nombre del proyecto:")
        if not ok or not name.strip():
            return

        template_path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar plantilla del dossier", "", "Archivos PDF (*.pdf)"
        )
        if not template_path:
            return

        project = self.project_service.new_project(name.strip())
        try:
            self._load_template_into_project(project, template_path)
        except (pdf_engine.PDFOpenError, pdf_engine.PDFPasswordProtectedError) as exc:
            QMessageBox.critical(self, "Error al leer la plantilla", str(exc))
            return

        self.project = project
        self.current_section_id = None
        self._dirty = False
        self._refresh_ui()

    def _load_template_into_project(self, project, template_path: str) -> None:
        toc = pdf_engine.extract_toc(template_path)
        project.template_path = template_path
        project.template_page_count = pdf_engine.get_page_count(template_path)

        if toc:
            project.sections = build_section_tree_from_toc(toc)
        else:
            # Sin bookmarks: se crea una unica seccion cubriendo todo el documento
            # para que el usuario pueda reorganizar manualmente.
            project.sections = [
                SectionNode(title="Documentos", numbering="1", level=1, template_page_index=0)
            ]
        logger.info("Plantilla cargada: %s (%d secciones detectadas)", template_path, len(project.sections))

    def open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Abrir proyecto", "", "Proyecto Dossier Builder (*.dossierproj)"
        )
        if not path:
            return
        try:
            self.project = self.project_service.open(path)
        except ProjectError as exc:
            QMessageBox.critical(self, "Error al abrir proyecto", str(exc))
            return
        self.settings_service.add_recent_project(path)
        self.current_section_id = None
        self._dirty = False
        self._refresh_ui()

    def save_project(self) -> None:
        if not self._require_project():
            return
        if self.project.project_file_path:
            self._save_to(self.project.project_file_path)
        else:
            self.save_project_as()

    def save_project_as(self) -> None:
        if not self._require_project():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar proyecto como", f"{self.project.name}.dossierproj", "Proyecto (*.dossierproj)"
        )
        if not path:
            return
        self._save_to(path)

    def _save_to(self, path: str) -> None:
        try:
            saved_path = self.project_service.save(self.project, path)
        except ProjectError as exc:
            QMessageBox.critical(self, "Error al guardar", str(exc))
            return
        self.settings_service.add_recent_project(str(saved_path))
        self.statusBar().showMessage(f"Proyecto guardado en {saved_path}", 5000)
        self._dirty = False
        self._refresh_ui()

    def edit_metadata(self) -> None:
        if not self._require_project():
            return
        dialog = MetadataDialog(self.project.metadata, self)
        if dialog.exec():
            self.project.metadata = dialog.result_metadata()
            self._touch_project()

    def edit_settings(self) -> None:
        if not self._require_project():
            return
        dialog = SettingsDialog(self.project.settings, self)
        if dialog.exec():
            self.project.settings = dialog.apply_to(self.project.settings)
            self._touch_project()

    def edit_preferences(self) -> None:
        """Preferencias globales (tema, DPI/nombre/salida por defecto), no
        atadas a un proyecto en particular."""
        dialog = PreferencesDialog(self.settings_service.settings, self)
        if dialog.exec():
            dialog.apply_to(self.settings_service.settings)
            self.settings_service.save()
            app = QApplication.instance()
            if app is not None:
                apply_theme(app, self.settings_service.settings.theme)

    def show_about_dialog(self) -> None:
        AboutDialog(self).exec()

    # ------------------------------------------------------------------
    # Secciones
    # ------------------------------------------------------------------
    def _on_section_selected(self, section_id: str) -> None:
        self.current_section_id = section_id
        self._refresh_document_list()

    def add_subsection(self) -> None:
        if not self._require_project():
            return
        parent = self._current_section()
        if parent is None:
            QMessageBox.information(self, "Subseccion", "Seleccione primero una seccion padre.")
            return

        dialog = NewSectionDialog(self)
        if not dialog.exec():
            return
        name = dialog.section_name()
        if not name:
            return

        child = SectionNode(
            title=name,
            level=parent.level + 1,
            order=len(parent.children),
            template_page_index=None,
            is_dynamic=True,
            parent_id=parent.id,
        )
        parent.children.append(child)
        renumber_sections(self.project.sections)
        self._touch_project()
        self._refresh_ui()
        self.tree.select_section(child.id)

    def remove_section(self) -> None:
        if not self._require_project():
            return
        section = self._current_section()
        if section is None:
            QMessageBox.information(self, "Eliminar seccion", "Seleccione primero una seccion.")
            return

        label = f"{section.numbering} {section.title}".strip()
        doc_count = section.total_documents()
        child_count = len(section.children)

        if section.is_dynamic:
            message = f"Eliminar la subseccion '{label}'?"
            if doc_count or child_count:
                message += (
                    f"\n\nSe eliminaran tambien sus {doc_count} documento(s) "
                    f"y {child_count} subseccion(es)."
                )
        else:
            message = (
                f"'{label}' proviene de un bookmark de la plantilla.\n\n"
                "Al eliminarla se quita su marcador y se eliminan del proyecto sus "
                f"{doc_count} documento(s) y {child_count} subseccion(es), pero la pagina "
                "separadora fisica de la plantilla seguira apareciendo en el dossier final "
                "(esta aplicacion nunca modifica el PDF de la plantilla en si).\n\n"
                "Continuar?"
            )

        confirm = QMessageBox.question(self, "Eliminar seccion", message)
        if confirm != QMessageBox.Yes:
            return

        container = self._find_section_container(section.id)
        if container is None:
            return
        container.remove(section)

        renumber_sections(self.project.sections)
        self._touch_project()
        self.current_section_id = None
        self._refresh_ui()

    def _find_section_container(self, section_id: str) -> Optional[list[SectionNode]]:
        """Devuelve la lista (raices del proyecto, o children de algun nodo)
        que contiene directamente al nodo con ``section_id``."""

        def search(nodes: list[SectionNode]) -> Optional[list[SectionNode]]:
            for node in nodes:
                if node.id == section_id:
                    return nodes
                found = search(node.children)
                if found is not None:
                    return found
            return None

        return search(self.project.sections)

    def _current_section(self) -> Optional[SectionNode]:
        if not self.project or not self.current_section_id:
            return None
        return self.project.find_section(self.current_section_id)

    # ------------------------------------------------------------------
    # Documentos
    # ------------------------------------------------------------------
    def _add_paths_to_section(self, paths: list[str], section: SectionNode) -> int:
        """Crea un DocumentItem por cada ruta, lo inspecciona (paginas,
        firma) y lo agrega al final de ``section``. Devuelve cuantos se
        agregaron. No toca el proyecto ni refresca la UI: eso queda a
        cargo del llamador, para poder agrupar varias inserciones.
        """
        for path in paths:
            doc = DocumentItem(source_path=path, order=len(section.documents))
            self._inspect_document(doc)
            section.documents.append(doc)
        return len(paths)

    def add_documents(self) -> None:
        section = self._current_section()
        if section is None:
            QMessageBox.information(self, "Agregar documento", "Seleccione primero una seccion.")
            return

        paths, _ = QFileDialog.getOpenFileNames(self, "Agregar documentos PDF", "", "Archivos PDF (*.pdf)")
        if not paths:
            return

        self._add_paths_to_section(paths, section)
        self._touch_project()
        self._refresh_ui()
        self.tree.select_section(section.id)

    def add_documents_from_folder(self) -> None:
        section = self._current_section()
        if section is None:
            QMessageBox.information(self, "Agregar carpeta", "Seleccione primero una seccion.")
            return

        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta con documentos PDF", "")
        if not folder:
            return

        pdf_paths = sorted(str(p) for p in Path(folder).rglob("*.pdf"))
        if not pdf_paths:
            QMessageBox.information(
                self, "Agregar carpeta", "No se encontraron archivos PDF en la carpeta seleccionada."
            )
            return

        self._add_paths_to_section(pdf_paths, section)
        self._touch_project()
        self._refresh_ui()
        self.tree.select_section(section.id)
        self.statusBar().showMessage(f"{len(pdf_paths)} documento(s) agregado(s) desde la carpeta.", 5000)

    def _on_files_dropped_on_document_list(self, paths: list[str]) -> None:
        """Archivos PDF arrastrados desde fuera de la app (p. ej. el
        Explorador de Windows) y soltados sobre la lista de documentos."""
        if not self._require_project():
            return
        section = self._current_section()
        if section is None:
            QMessageBox.information(
                self, "Agregar documentos", "Seleccione primero una seccion antes de arrastrar archivos."
            )
            return
        count = self._add_paths_to_section(paths, section)
        self._touch_project()
        self._refresh_ui()
        self.tree.select_section(section.id)
        self.statusBar().showMessage(f"{count} documento(s) agregado(s) por arrastrar y soltar.", 5000)

    def _on_files_dropped_on_section(self, section_id: str, paths: list[str]) -> None:
        """Archivos PDF arrastrados y soltados directamente sobre una
        seccion del arbol (sin necesidad de seleccionarla primero)."""
        if not self._require_project():
            return
        section = self.project.find_section(section_id)
        if section is None:
            return
        count = self._add_paths_to_section(paths, section)
        self._touch_project()
        self._refresh_ui()
        self.tree.select_section(section.id)
        self.statusBar().showMessage(f"{count} documento(s) agregado(s) por arrastrar y soltar.", 5000)

    def auto_distribute_documents(self) -> None:
        if not self._require_project():
            return
        if not self.project.sections:
            QMessageBox.information(self, "Distribuir documentos", "Cargue primero una plantilla con secciones.")
            return

        paths, _ = QFileDialog.getOpenFileNames(
            self, "Seleccionar documentos a distribuir", "", "Archivos PDF (*.pdf)"
        )
        if not paths:
            return

        dialog = AutoDistributeDialog(paths, self.project.sections, self)
        if not dialog.exec():
            return

        assignments = dialog.result_assignments()
        touched_section_id = None
        added_count = 0
        for path, section_id in assignments.items():
            if not section_id:
                continue
            section = self.project.find_section(section_id)
            if section is None:
                continue
            doc = DocumentItem(source_path=path, order=len(section.documents))
            self._inspect_document(doc)
            section.documents.append(doc)
            touched_section_id = section_id
            added_count += 1

        if added_count == 0:
            return

        self._touch_project()
        self._refresh_ui()
        if touched_section_id:
            self.tree.select_section(touched_section_id)
        self.statusBar().showMessage(f"{added_count} documento(s) distribuido(s) automaticamente.", 5000)

    def _compute_preview_rows(self):
        """Devuelve la lista de PreviewRow del dossier actual, o None si no
        se pudo calcular (y ya se mostro el mensaje de error correspondiente)."""
        if not self.project.template_path:
            QMessageBox.information(self, "Vista previa del dossier", "Cargue primero una plantilla.")
            return None
        try:
            builder = DossierBuilder(self.project)
            return builder.build_preview_outline()
        except pdf_engine.PDFOpenError as exc:
            QMessageBox.critical(self, "Vista previa del dossier", str(exc))
            return None

    def preview_dossier_outline(self) -> None:
        if not self._require_project():
            return
        rows = self._compute_preview_rows()
        if rows is None:
            return
        DossierOutlinePreviewDialog(rows, self).exec()

    def preview_dossier_thumbnails(self) -> None:
        if not self._require_project():
            return
        rows = self._compute_preview_rows()
        if rows is None:
            return
        DossierThumbnailPreviewDialog(rows, self).exec()

    def _inspect_document(self, doc: DocumentItem) -> None:
        """Completa metadatos basicos y deteccion de firma al agregar un documento."""
        path = Path(doc.source_path)
        try:
            doc.file_size_bytes = path.stat().st_size
        except OSError as exc:
            doc.status = DocumentStatus.MISSING
            doc.error_message = str(exc)
            return

        try:
            doc.page_count = pdf_engine.get_page_count(str(path))
        except pdf_engine.PDFPasswordProtectedError:
            doc.status = DocumentStatus.PASSWORD_PROTECTED
            doc.error_message = "El PDF esta protegido con contrasena."
            return
        except pdf_engine.PDFOpenError as exc:
            doc.status = DocumentStatus.CORRUPT
            doc.error_message = str(exc)
            return

        try:
            signature_info = detect_signatures(str(path))
            doc.has_signature = signature_info.has_signature
            doc.signature_details = signature_info.details
        except Exception as exc:  # noqa: BLE001 - la deteccion nunca debe bloquear el agregado
            logger.warning("No se pudo analizar firmas de '%s': %s", path, exc)
            doc.has_signature = None

        doc.status = DocumentStatus.OK

    def _refresh_document_list(self) -> None:
        section = self._current_section()
        if section is None:
            self.section_label.setText("Seleccione una seccion")
            self.doc_list.clear()
            return
        label = f"{section.numbering} {section.title}".strip()
        self.section_label.setText(f"{label}  ({len(section.documents)} documento(s))")
        self.doc_list.load_documents(section.documents)

    def _on_documents_reordered(self) -> None:
        section = self._current_section()
        if section is None:
            return
        by_id = {doc.id: doc for doc in section.documents}
        new_order = [by_id[doc_id] for doc_id in self.doc_list.ordered_document_ids() if doc_id in by_id]
        for index, doc in enumerate(new_order):
            doc.order = index
        section.documents = new_order
        self._touch_project()

    def _move_selected(self, direction: int) -> None:
        section = self._current_section()
        if section is None:
            return
        selected_ids = self.doc_list.selected_document_ids()
        if len(selected_ids) != 1:
            return
        doc_id = selected_ids[0]
        index = next((i for i, d in enumerate(section.documents) if d.id == doc_id), None)
        if index is None:
            return
        new_index = index + direction
        if not (0 <= new_index < len(section.documents)):
            return
        section.documents[index], section.documents[new_index] = (
            section.documents[new_index],
            section.documents[index],
        )
        for i, doc in enumerate(section.documents):
            doc.order = i
        self._touch_project()
        self._refresh_document_list()

    def remove_selected_documents(self) -> None:
        section = self._current_section()
        if section is None:
            return
        selected_ids = set(self.doc_list.selected_document_ids())
        if not selected_ids:
            return
        confirm = QMessageBox.question(
            self, "Eliminar documentos", f"Eliminar {len(selected_ids)} documento(s) de la seccion?"
        )
        if confirm != QMessageBox.Yes:
            return
        section.documents = [d for d in section.documents if d.id not in selected_ids]
        for i, doc in enumerate(section.documents):
            doc.order = i
        self._touch_project()
        self._refresh_ui()

    def _move_or_copy_selected_documents(self, copy: bool) -> None:
        """Mueve (o copia) los documentos seleccionados a otra seccion,
        sin tener que eliminarlos y volver a agregarlos desde cero."""
        section = self._current_section()
        if section is None:
            return
        selected_ids = set(self.doc_list.selected_document_ids())
        if not selected_ids:
            return
        selected_docs = [d for d in section.documents if d.id in selected_ids]
        if not selected_docs:
            return

        options = flatten_section_options(self.project.sections)
        if not options:
            return
        labels = [label for label, _ in options]
        current_label = next((label for label, sid in options if sid == section.id), labels[0])
        start_index = labels.index(current_label) if current_label in labels else 0

        title = "Copiar documento(s)" if copy else "Mover documento(s)"
        chosen_label, ok = QInputDialog.getItem(
            self, title, "Seccion destino:", labels, current=start_index, editable=False
        )
        if not ok:
            return
        target_id = next((sid for label, sid in options if label == chosen_label), None)
        if target_id is None:
            return
        if target_id == section.id:
            QMessageBox.information(self, title, "Esa ya es la seccion actual del documento.")
            return
        target_section = self.project.find_section(target_id)
        if target_section is None:
            return

        if copy:
            for doc in selected_docs:
                new_doc = DocumentItem.from_dict(doc.to_dict())
                new_doc.id = str(uuid.uuid4())
                new_doc.order = len(target_section.documents)
                target_section.documents.append(new_doc)
        else:
            section.documents = [d for d in section.documents if d.id not in selected_ids]
            for i, doc in enumerate(section.documents):
                doc.order = i
            for doc in selected_docs:
                doc.order = len(target_section.documents)
                target_section.documents.append(doc)

        self._touch_project()
        self._refresh_ui()
        self.tree.select_section(target_id)
        verb = "copiado(s)" if copy else "movido(s)"
        self.statusBar().showMessage(f"{len(selected_docs)} documento(s) {verb} a '{chosen_label}'.", 5000)

    def _selected_document(self) -> Optional[DocumentItem]:
        section = self._current_section()
        if section is None:
            return None
        ids = self.doc_list.selected_document_ids()
        if len(ids) != 1:
            return None
        return next((d for d in section.documents if d.id == ids[0]), None)

    def preview_selected_document(self) -> None:
        doc = self._selected_document()
        if doc is None:
            return
        path = doc.flattened_path or doc.source_path
        if not Path(path).exists():
            QMessageBox.warning(self, "Vista previa", f"El archivo no existe: {path}")
            return
        PdfPreviewDialog(path, self).exec()

    def open_selected_document_external(self) -> None:
        doc = self._selected_document()
        if doc is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(doc.source_path))

    def open_selected_document_folder(self) -> None:
        doc = self._selected_document()
        if doc is None:
            return
        folder = str(Path(doc.source_path).parent)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _show_treatment_menu(self) -> None:
        if not self.doc_list.selected_document_ids():
            QMessageBox.information(self, "Tratamiento de firma", "Seleccione uno o mas documentos.")
            return

        menu = QMenu(self)
        act_keep = menu.addAction("Conservar original")
        act_flatten = menu.addAction("Aplanar para dossier")
        act_auto = menu.addAction("Automatico (segun deteccion de firma)")
        chosen = menu.exec(self.btn_treatment.mapToGlobal(self.btn_treatment.rect().bottomLeft()))
        if chosen is None:
            return
        value = {
            act_keep: SignatureTreatment.KEEP_ORIGINAL,
            act_flatten: SignatureTreatment.FLATTEN,
            act_auto: SignatureTreatment.AUTO,
        }[chosen]
        self._apply_treatment_to_selected(value)

    def _apply_treatment_to_selected(self, value: SignatureTreatment) -> None:
        section = self._current_section()
        if section is None:
            return
        selected_ids = set(self.doc_list.selected_document_ids())
        if not selected_ids:
            return

        if value == SignatureTreatment.FLATTEN:
            QMessageBox.information(
                self,
                "Aplanado de firma",
                "Este documento contiene (o podria contener) una firma digital. Para incluirlo en el "
                "dossier se generara una representacion plana (imagen de alta resolucion). El archivo "
                "original firmado permanecera sin modificaciones.",
            )

        for doc in section.documents:
            if doc.id in selected_ids:
                doc.signature_treatment = value
        self._touch_project()
        self._refresh_document_list()

    def _show_document_context_menu(self, pos) -> None:
        if self._current_section() is None:
            return
        item = self.doc_list.itemAt(pos)
        if item is not None and item not in self.doc_list.selectedItems():
            self.doc_list.setCurrentItem(item)
        if not self.doc_list.selectedItems():
            return

        menu = QMenu(self)
        menu.addAction("Vista previa", self.preview_selected_document)
        menu.addAction("Abrir documento", self.open_selected_document_external)
        menu.addAction("Abrir ubicacion", self.open_selected_document_folder)
        menu.addSeparator()

        treatment_menu = menu.addMenu("Tratamiento de firma")
        treatment_menu.addAction(
            "Conservar original", lambda: self._apply_treatment_to_selected(SignatureTreatment.KEEP_ORIGINAL)
        )
        treatment_menu.addAction(
            "Aplanar para dossier", lambda: self._apply_treatment_to_selected(SignatureTreatment.FLATTEN)
        )
        treatment_menu.addAction(
            "Automatico (segun deteccion de firma)", lambda: self._apply_treatment_to_selected(SignatureTreatment.AUTO)
        )
        menu.addSeparator()

        menu.addAction("Subir", lambda: self._move_selected(-1))
        menu.addAction("Bajar", lambda: self._move_selected(1))
        menu.addSeparator()
        menu.addAction("Mover a seccion...", lambda: self._move_or_copy_selected_documents(copy=False))
        menu.addAction("Copiar a seccion...", lambda: self._move_or_copy_selected_documents(copy=True))
        menu.addSeparator()
        menu.addAction("Eliminar", self.remove_selected_documents)

        menu.exec(self.doc_list.viewport().mapToGlobal(pos))

    def _show_section_context_menu(self, pos) -> None:
        if not self._require_project():
            return
        item = self.tree.itemAt(pos)
        if item is None:
            return
        self.tree.setCurrentItem(item)
        section = self._current_section()
        if section is None:
            return

        menu = QMenu(self)
        menu.addAction("Agregar subseccion", self.add_subsection)
        menu.addAction("Renombrar seccion", self._rename_current_section)
        menu.addSeparator()
        menu.addAction("Eliminar seccion", self.remove_section)

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _rename_current_section(self) -> None:
        section = self._current_section()
        if section is None:
            return
        new_title, ok = QInputDialog.getText(self, "Renombrar seccion", "Nuevo nombre:", text=section.title)
        if not ok or not new_title.strip():
            return
        section.title = new_title.strip()
        self._touch_project()
        self._refresh_ui()
        self.tree.select_section(section.id)

    # ------------------------------------------------------------------
    # Validacion y generacion
    # ------------------------------------------------------------------
    def validate_dossier(self) -> None:
        if not self._require_project():
            return
        report = validate_project(self.project)
        ValidationResultsDialog(report, self).exec()

    def generate_dossier(self) -> None:
        if not self._require_project():
            return

        report = validate_project(self.project)
        if not report.can_generate:
            ValidationResultsDialog(report, self).exec()
            return
        if report.warnings:
            proceed = QMessageBox.question(
                self,
                "Advertencias encontradas",
                f"Se encontraron {len(report.warnings)} advertencia(s). Desea continuar de todas formas?",
            )
            if proceed != QMessageBox.Yes:
                return

        output_root = QFileDialog.getExistingDirectory(
            self, "Carpeta de salida del dossier", self.project.settings.output_dir or ""
        )
        if not output_root:
            return
        self.project.settings.output_dir = output_root

        suggested_name = render_naming_pattern(
            self.project.settings.output_naming_pattern, self.project.metadata.as_naming_context()
        )

        output_filename: Optional[str] = None
        if self.project.generation_count > 0 and self.project.last_output_filename:
            # Ya se genero antes: preguntar si se mantiene el mismo nombre o
            # se cambia, en vez de solo ofrecer un campo de texto en blanco.
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Question)
            box.setWindowTitle("Nombre del dossier")
            box.setText(
                f"Este proyecto ya se genero antes (generacion N.° {self.project.generation_count}), "
                f"la ultima vez como:\n\n\"{self.project.last_output_filename}\"\n\n"
                "Desea mantener ese mismo nombre para esta nueva generacion, o cambiarlo?"
            )
            keep_btn = box.addButton("Mantener nombre", QMessageBox.AcceptRole)
            box.addButton("Cambiar nombre", QMessageBox.ActionRole)
            cancel_btn = box.addButton("Cancelar", QMessageBox.RejectRole)
            box.setDefaultButton(keep_btn)
            box.exec()
            clicked = box.clickedButton()
            if clicked == cancel_btn:
                return
            if clicked == keep_btn:
                output_filename = self.project.last_output_filename
            # "Cambiar nombre" (o cualquier otro caso): cae al dialogo de texto de abajo.

        if output_filename is None:
            output_filename, ok = QInputDialog.getText(
                self,
                "Nombre del dossier",
                "Nombre o codigo con el que se guardara el archivo generado:",
                text=suggested_name,
            )
            if not ok or not output_filename.strip():
                return

        self._progress_dialog = QProgressDialog("Preparando generacion...", "Cancelar", 0, 100, self)
        self._progress_dialog.setWindowTitle("Generando dossier")
        self._progress_dialog.setWindowModality(Qt.WindowModal)
        self._progress_dialog.setMinimumDuration(0)
        self._progress_dialog.canceled.connect(self._cancel_generation)

        self._generation_worker = GenerationWorker(self.project, output_root, output_filename=output_filename)
        self._generation_worker.progress.connect(self._on_generation_progress)
        self._generation_worker.finished_ok.connect(self._on_generation_finished)
        self._generation_worker.failed.connect(self._on_generation_failed)
        self._generation_worker.start()

        self.generate_action.setEnabled(False)

    def _cancel_generation(self) -> None:
        if self._generation_worker:
            self._generation_worker.cancel()

    def _on_generation_progress(self, current: int, total: int, message: str) -> None:
        if not self._progress_dialog:
            return
        self._progress_dialog.setMaximum(max(total, 1))
        self._progress_dialog.setValue(min(current, total))
        self._progress_dialog.setLabelText(f"{message}  ({current}/{total})")

    def _on_generation_finished(self, result: GenerationResult) -> None:
        if self._progress_dialog:
            self._progress_dialog.close()
        self.generate_action.setEnabled(True)

        # DossierBuilder.generate() ya actualizo generation_count /
        # last_output_filename / last_generated_at en self.project (mismo
        # objeto usado por el hilo de generacion); solo falta marcar el
        # proyecto como modificado para que se ofrezca guardar ese estado.
        self._touch_project()

        self.database.record_generation(
            project_id=self.project.id,
            output_path=result.output_pdf_path,
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            total_pages=result.total_pages,
            total_documents=result.total_documents,
            flattened_count=result.flattened_count,
            sha256_final=result.sha256_final,
            had_errors=False,
        )

        answer = QMessageBox.information(
            self,
            "Dossier generado",
            f"Dossier generado correctamente (generacion N.° {result.generation_number} de este proyecto):\n"
            f"{result.output_pdf_path}\n\n"
            f"Paginas: {result.total_pages}\n"
            f"Documentos: {result.total_documents}\n"
            f"Documentos aplanados (firma): {result.flattened_count}\n"
            f"SHA-256: {result.sha256_final}\n\n"
            "Desea abrir la carpeta de salida?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(result.output_pdf_path).parent)))

    def _on_generation_failed(self, message: str) -> None:
        if self._progress_dialog:
            self._progress_dialog.close()
        self.generate_action.setEnabled(True)
        QMessageBox.critical(self, "Error al generar el dossier", message)

    # ------------------------------------------------------------------
    # Utilidades generales
    # ------------------------------------------------------------------
    def _require_project(self) -> bool:
        if self.project is None:
            QMessageBox.information(self, "Sin proyecto", "Cree o abra un proyecto primero.")
            return False
        return True

    def _refresh_ui(self) -> None:
        has_project = self.project is not None
        for widget in (
            self.btn_add_docs,
            self.btn_add_folder,
            self.btn_add_subsection,
            self.btn_remove_section,
            self.btn_move_up,
            self.btn_move_down,
            self.btn_remove,
            self.btn_preview,
            self.btn_treatment,
            self.btn_open_external,
            self.btn_open_folder,
        ):
            widget.setEnabled(has_project)

        if not has_project:
            self.setWindowTitle("Dossier Builder QA/QC")
            self.tree.clear()
            self.doc_list.clear()
            self.section_label.setText("Cree o abra un proyecto para comenzar")
            self.statusBar().clearMessage()
            return

        self.setWindowTitle(f"Dossier Builder QA/QC - {self.project.name}")
        self.tree.load_sections(self.project.sections)
        self._refresh_document_list()

        total_docs = self.project.total_documents()
        signed_docs = sum(
            1 for s in self.project.iter_all_sections() for d in s.documents if d.has_signature
        )
        self.statusBar().showMessage(
            f"{total_docs} documento(s) | {signed_docs} con firma detectada | "
            f"plantilla: {Path(self.project.template_path).name if self.project.template_path else '-'}"
        )
