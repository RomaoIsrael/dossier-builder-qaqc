"""Ventana principal de Dossier Builder QA/QC."""
from __future__ import annotations

import getpass
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from PySide6.QtCore import QSize, QThread, QUrl, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QSlider,
    QSplitter,
    QStatusBar,
    QStyle,
    QToolBar,
    QToolButton,
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
    AuditLogDialog,
    AutoDistributeDialog,
    DossierOutlinePreviewDialog,
    DossierThumbnailPreviewDialog,
    MetadataDialog,
    NewSectionDialog,
    PdfPreviewDialog,
    PreferencesDialog,
    SettingsDialog,
    UserManualDialog,
    ValidationResultsDialog,
    flatten_section_options,
    render_pdf_page_image,
)
from app.ui.theme import apply_theme
from app.ui.widgets import DocumentListWidget, RailEntry, SectionTreeWidget, ThumbnailRailWidget
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


class ThumbnailRailWorker(QThread):
    """Renderiza en un hilo aparte todas las miniaturas del panel lateral,
    para no congelar la interfaz mientras se abren y rasterizan los PDF.

    Recibe ``specs`` ya armados por la ventana principal (rutas de archivo,
    ids, textos -- datos inmutables de solo lectura) en vez de una
    referencia viva al proyecto: asi el hilo de fondo nunca toca el modelo
    del proyecto mientras el usuario lo sigue editando desde la interfaz.
    Usa ``QImage`` (seguro entre hilos) en vez de ``QPixmap`` (que solo debe
    crearse en el hilo principal); la conversion final a QPixmap la hace
    quien reciba la señal ``finished_ok``.
    """

    finished_ok = Signal(list)

    def __init__(self, specs: list[tuple], render_width: int):
        super().__init__()
        self._specs = specs
        self._render_width = render_width

    def run(self) -> None:  # noqa: D102 - metodo estandar de QThread
        rendered: list[tuple] = []
        template_doc: Optional[fitz.Document] = None
        template_open_failed = False

        for spec in self._specs:
            kind = spec[0]
            if kind == "template":
                _, template_path, page_index = spec
                if template_doc is None and not template_open_failed and template_path:
                    try:
                        template_doc = fitz.open(template_path)
                    except Exception:  # noqa: BLE001 - una plantilla danada no debe romper el panel
                        template_open_failed = True
                image = None
                if template_doc is not None:
                    image = render_pdf_page_image(template_doc, page_index, self._render_width)
                rendered.append((None, None, page_index, f"Plantilla\nPagina {page_index + 1}", image, False))
            elif kind == "doc":
                _, document_id, section_id, section_label, name, source_path, excluded = spec
                if not source_path or not Path(source_path).exists():
                    caption = f"{section_label}\n{name}\n(archivo no disponible)"
                    rendered.append((document_id, section_id, 0, caption, None, False))
                    continue
                try:
                    source_doc = fitz.open(source_path)
                except Exception:  # noqa: BLE001 - un archivo danado no debe romper el panel
                    caption = f"{section_label}\n{name}\n(no se pudo abrir)"
                    rendered.append((document_id, section_id, 0, caption, None, False))
                    continue
                try:
                    total_pages = source_doc.page_count
                    for page_index in range(total_pages):
                        is_excluded = page_index in excluded
                        image = render_pdf_page_image(source_doc, page_index, self._render_width)
                        caption = f"{section_label}\n{name}"
                        if total_pages > 1:
                            caption += f"\nHoja {page_index + 1} de {total_pages}"
                        if is_excluded:
                            caption += "\n(excluida del dossier)"
                        rendered.append((document_id, section_id, page_index, caption, image, is_excluded))
                finally:
                    source_doc.close()

        if template_doc is not None:
            template_doc.close()

        self.finished_ok.emit(rendered)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dossier Builder QA/QC")
        self.resize(1280, 820)
        # Con la ventana mas chica que esto, los tres paneles (secciones,
        # documentos, miniaturas) ya no entran con un ancho legible; mejor
        # no dejar achicar tanto la ventana que deje de verse bien.
        self.setMinimumSize(1000, 650)

        self.database = DatabaseService()
        self.project_service = ProjectService(database=self.database)
        self.settings_service = SettingsService()

        self.project = None
        self.current_section_id: Optional[str] = None
        self._generation_worker: Optional[GenerationWorker] = None
        self._progress_dialog: Optional[QProgressDialog] = None
        self._dirty = False  # True si hay cambios del proyecto sin guardar
        # Evita bucles al sincronizar la seleccion entre el arbol de
        # secciones, la lista de documentos y el panel de miniaturas.
        self._syncing_selection = False
        self._thumbnail_worker: Optional[ThumbnailRailWorker] = None

        self._build_toolbar()
        self._build_central_widget()
        self.setStatusBar(QStatusBar())

        self._refresh_ui()

    def _log_action(self, action: str, details: str = "") -> None:
        """Registra en el historial del proyecto quien (usuario de Windows)
        hizo que accion, para poder saber que modifico cada persona que
        haya abierto el proyecto, aunque sea desde otra computadora."""
        if self.project is None:
            return
        self.project.log_action(getpass.getuser(), action, details)

    def _touch_project(self, action: str = "", details: str = "") -> None:
        """Marca el proyecto como modificado (fecha + estado 'sin guardar')
        y, si se indica una accion, la agrega al historial de cambios.

        Se usa en vez de llamar directamente a ``self.project.touch()`` para
        que la ventana sepa, ademas, que hay cambios pendientes y pregunte
        antes de cerrarse si el usuario no los guardo.
        """
        self.project.touch()
        self._dirty = True
        if action:
            self._log_action(action, details)

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

        self.recent_projects_menu = QMenu(self)
        self.recent_projects_menu.aboutToShow.connect(self._populate_recent_projects_menu)
        recent_button = QToolButton()
        recent_button.setText("Proyectos recientes")
        recent_button.setToolTip("Ver y abrir proyectos usados recientemente")
        recent_button.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))
        recent_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        recent_button.setPopupMode(QToolButton.InstantPopup)
        recent_button.setMenu(self.recent_projects_menu)
        toolbar_top.addWidget(recent_button)

        add_action(toolbar_top, "Guardar", self.save_project, QStyle.SP_DialogSaveButton)
        add_action(toolbar_top, "Guardar como...", self.save_project_as, QStyle.SP_DriveFDIcon)
        toolbar_top.addSeparator()
        add_action(toolbar_top, "Metadatos", self.edit_metadata, QStyle.SP_FileDialogInfoView)
        add_action(toolbar_top, "Configuracion", self.edit_settings, QStyle.SP_FileDialogDetailedView)
        add_action(toolbar_top, "Preferencias", self.edit_preferences, QStyle.SP_ComputerIcon)
        add_action(toolbar_top, "Historial de cambios", self.show_audit_log, QStyle.SP_FileDialogListView)
        toolbar_top.addSeparator()
        add_action(toolbar_top, "Manual de Usuario", self.show_user_manual, QStyle.SP_DialogHelpButton)
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
        # Que ningun panel se pueda "colapsar" arrastrando el separador (a
        # veces quedaba practicamente en 0 de ancho y ya no se lo podia
        # volver a ensanchar arrastrando).
        splitter.setChildrenCollapsible(False)

        # -- Panel izquierdo: arbol de secciones ---------------------------
        self.tree = SectionTreeWidget()
        self.tree.section_selected.connect(self._on_section_selected)
        self.tree.files_dropped_on_section.connect(self._on_files_dropped_on_section)
        self.tree.customContextMenuRequested.connect(self._show_section_context_menu)
        self.tree.delete_requested.connect(self.remove_section)
        # Ancho minimo fijo: sin esto, el titulo de una seccion muy larga en
        # el panel central podia forzar que este panel se achicara solo
        # (ver nota en self.section_label mas abajo).
        self.tree.setMinimumWidth(220)
        splitter.addWidget(self.tree)

        # -- Panel central: documentos de la seccion seleccionada -----------
        center = QWidget()
        center_layout = QVBoxLayout(center)

        self.section_label = QLabel("Seleccione una seccion")
        self.section_label.setStyleSheet("font-weight: 600; font-size: 13pt; padding: 4px 2px;")
        # Titulos de seccion largos (ej. "2.4 EQUIPO BES, CABLE ELECTRICO,
        # PROTECTORES DE CABLE Y CONECTOR ELECTRICO DE SUPERFICIE.") sin
        # ajuste de linea forzaban a este QLabel a pedir un ancho enorme de
        # una sola linea, y el splitter le quitaba ese espacio al panel de
        # secciones (achicandolo solo, sin que se pudiera volver a
        # ensanchar). Con ajuste de linea, el titulo pasa a varias lineas en
        # vez de estirar el panel.
        self.section_label.setWordWrap(True)
        center_layout.addWidget(self.section_label)

        self.doc_list = DocumentListWidget()
        self.doc_list.order_changed.connect(self._on_documents_reordered)
        self.doc_list.itemDoubleClicked.connect(lambda _item: self.preview_selected_document())
        self.doc_list.files_dropped.connect(self._on_files_dropped_on_document_list)
        self.doc_list.customContextMenuRequested.connect(self._show_document_context_menu)
        self.doc_list.delete_requested.connect(self.remove_selected_documents)
        self.doc_list.itemSelectionChanged.connect(self._on_document_selection_changed)
        center_layout.addWidget(self.doc_list, stretch=1)

        buttons_row1 = QHBoxLayout()
        self.btn_add_docs = QPushButton("+ Agregar documento(s)")
        self.btn_add_docs.clicked.connect(self.add_documents)
        self.btn_add_folder = QPushButton("+ Agregar carpeta")
        self.btn_add_folder.clicked.connect(self.add_documents_from_folder)
        self.btn_add_subsection = QPushButton("+ Agregar subseccion")
        self.btn_add_subsection.clicked.connect(self.add_subsection)
        self.btn_no_aplica = QPushButton("NO APLICA")
        self.btn_no_aplica.setCheckable(True)
        self.btn_no_aplica.setToolTip(
            "Marcar esta seccion/subseccion como 'No aplica': se agrega una hoja generica que lo "
            "indica. Se puede desmarcar en cualquier momento para revertirlo."
        )
        self.btn_no_aplica.toggled.connect(self._on_no_aplica_toggled)
        self.btn_remove_section = QPushButton("Eliminar seccion")
        self.btn_remove_section.clicked.connect(self.remove_section)
        buttons_row1.addWidget(self.btn_add_docs)
        buttons_row1.addWidget(self.btn_add_folder)
        buttons_row1.addWidget(self.btn_add_subsection)
        buttons_row1.addWidget(self.btn_no_aplica)
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

        # -- Panel derecho: miniaturas de todo el dossier --------------------
        thumb_container = QWidget()
        thumb_layout = QVBoxLayout(thumb_container)

        thumb_header = QHBoxLayout()
        thumb_label = QLabel("Miniaturas del dossier")
        thumb_label.setStyleSheet("font-weight: 600; padding: 4px 2px;")
        thumb_header.addWidget(thumb_label, stretch=1)
        thumb_header.addWidget(QLabel("Tamano:"))
        self.thumbnail_zoom_slider = QSlider(Qt.Horizontal)
        self.thumbnail_zoom_slider.setRange(ThumbnailRailWidget.MIN_ZOOM, ThumbnailRailWidget.MAX_ZOOM)
        self.thumbnail_zoom_slider.setFixedWidth(90)
        self.thumbnail_zoom_slider.setToolTip("Agrandar o achicar las miniaturas")
        thumb_header.addWidget(self.thumbnail_zoom_slider)
        thumb_layout.addLayout(thumb_header)

        # Indicador de posicion estilo Acrobat/Foxit ("Hoja 45 de 230"),
        # siempre reflejando la miniatura actualmente seleccionada dentro
        # de todo el dossier.
        self.thumbnail_position_label = QLabel("")
        self.thumbnail_position_label.setAlignment(Qt.AlignCenter)
        self.thumbnail_position_label.setStyleSheet("color: palette(mid); font-size: 9pt; padding: 0 2px 4px 2px;")
        thumb_layout.addWidget(self.thumbnail_position_label)

        # Barra de progreso indeterminada: se muestra mientras el hilo de
        # fondo esta renderizando las miniaturas, para que quede claro que
        # el programa esta trabajando y no que se congelo.
        self.thumbnail_busy_bar = QProgressBar()
        self.thumbnail_busy_bar.setRange(0, 0)
        self.thumbnail_busy_bar.setTextVisible(False)
        self.thumbnail_busy_bar.setFixedHeight(4)
        self.thumbnail_busy_bar.setVisible(False)
        thumb_layout.addWidget(self.thumbnail_busy_bar)

        self.thumbnail_rail = ThumbnailRailWidget()
        initial_zoom = self.settings_service.settings.thumbnail_rail_zoom or ThumbnailRailWidget.DEFAULT_ZOOM
        self.thumbnail_zoom_slider.setValue(initial_zoom)
        self.thumbnail_rail.set_thumbnail_zoom(initial_zoom)
        self.thumbnail_zoom_slider.valueChanged.connect(self.thumbnail_rail.set_thumbnail_zoom)
        self.thumbnail_zoom_slider.sliderReleased.connect(self._save_thumbnail_zoom)
        self.thumbnail_rail.thumbnail_activated.connect(self._on_thumbnail_activated)
        self.thumbnail_rail.delete_requested.connect(self._on_thumbnail_delete_requested)
        self.thumbnail_rail.customContextMenuRequested.connect(self._show_thumbnail_context_menu)
        self.thumbnail_rail.currentItemChanged.connect(self._on_thumbnail_current_changed)
        thumb_layout.addWidget(self.thumbnail_rail, stretch=1)

        splitter.addWidget(thumb_container)
        splitter.setSizes([320, 780, 260])
        # Al agrandar o achicar la ventana, que el panel central (la lista
        # de documentos, que ya tiene su propia barra de desplazamiento) sea
        # el que absorbe ese cambio de espacio, y no el arbol de secciones
        # ni el panel de miniaturas -- asi estos dos mantienen un ancho
        # utilizable en vez de terminar aplastados en una ventana chica.
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)

        self.setCentralWidget(splitter)

    # ------------------------------------------------------------------
    # Gestion de proyectos
    # ------------------------------------------------------------------
    def new_project(self) -> None:
        name, ok = QInputDialog.getText(self, "Nuevo proyecto", "Nombre del proyecto:")
        if not ok or not name.strip():
            return

        # Antes de abrir el explorador de archivos, se aclara que lo que se
        # va a elegir es la PLANTILLA (caratula + indice + paginas
        # separadoras con bookmarks), no un documento cualquiera: sin este
        # aviso no queda claro que archivo hay que buscar ni para que.
        QMessageBox.information(
            self,
            "Elegir plantilla",
            "A continuacion, elegir plantilla: seleccione el PDF que se usara como plantilla "
            "del dossier (el que tiene la caratula, el indice y las paginas separadoras de cada "
            "seccion, con sus bookmarks).\n\n"
            "Los documentos individuales de cada seccion se agregan despues, ya con el "
            "proyecto creado.",
        )

        template_path, _ = QFileDialog.getOpenFileName(
            self, "Elegir plantilla del dossier (PDF)", "", "Archivos PDF (*.pdf)"
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
        self._open_project_path(path)

    def _open_project_path(self, path: str) -> None:
        try:
            self.project = self.project_service.open(path)
        except ProjectError as exc:
            QMessageBox.critical(self, "Error al abrir proyecto", str(exc))
            return
        self.settings_service.add_recent_project(path)
        self.current_section_id = None
        self._dirty = False
        self._refresh_ui()

    def _populate_recent_projects_menu(self) -> None:
        """Reconstruye el menu "Proyectos recientes" cada vez que se va a
        mostrar, para que siempre refleje la lista actual y marque cual es
        el proyecto abierto ahora mismo (si esta entre los recientes)."""
        menu = self.recent_projects_menu
        menu.clear()
        recents = self.settings_service.settings.recent_projects
        if not recents:
            action = menu.addAction("(No hay proyectos recientes)")
            action.setEnabled(False)
            return

        current_path = None
        if self.project and self.project.project_file_path:
            current_path = str(Path(self.project.project_file_path).resolve())

        for path in recents:
            exists = Path(path).exists()
            label = Path(path).stem
            if current_path and exists and str(Path(path).resolve()) == current_path:
                label += "  <- proyecto actual"
            if not exists:
                label += "  (no encontrado)"
            action = menu.addAction(label)
            action.setEnabled(exists)
            action.setToolTip(path)
            action.triggered.connect(lambda checked=False, p=path: self._open_recent_project(p))

        menu.addSeparator()
        clear_action = menu.addAction("Limpiar historial")
        clear_action.triggered.connect(self._clear_recent_projects)

    def _open_recent_project(self, path: str) -> None:
        if not Path(path).exists():
            QMessageBox.warning(
                self, "Proyectos recientes", f"No se encontro el archivo:\n{path}"
            )
            return
        self._open_project_path(path)

    def _clear_recent_projects(self) -> None:
        self.settings_service.settings.recent_projects = []
        self.settings_service.save()

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
        self._log_action("Guardar proyecto", str(saved_path))
        self._refresh_ui()

    def edit_metadata(self) -> None:
        if not self._require_project():
            return
        dialog = MetadataDialog(self.project.metadata, self)
        if dialog.exec():
            self.project.metadata = dialog.result_metadata()
            self._touch_project("Editar metadatos")

    def edit_settings(self) -> None:
        if not self._require_project():
            return
        dialog = SettingsDialog(self.project.settings, self)
        if dialog.exec():
            self.project.settings = dialog.apply_to(self.project.settings)
            self._touch_project("Editar configuracion")

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

    def show_user_manual(self) -> None:
        UserManualDialog(self).exec()

    def show_audit_log(self) -> None:
        if not self._require_project():
            return
        AuditLogDialog(self.project.audit_log, self).exec()

    # ------------------------------------------------------------------
    # Secciones
    # ------------------------------------------------------------------
    def _on_section_selected(self, section_id: str) -> None:
        self.current_section_id = section_id
        self._refresh_document_list()
        if not self._syncing_selection:
            self.thumbnail_rail.scroll_to_section(section_id)

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
        parent_label = f"{parent.numbering} {parent.title}".strip()
        self._touch_project("Agregar subseccion", f"'{name}' bajo '{parent_label}'")
        self._refresh_ui()
        self.tree.select_section(child.id)

    def _resolve_no_aplica_template_path(self) -> Optional[str]:
        """Devuelve la ruta del PDF a usar para las hojas 'NO APLICA'. Si no
        hay una predeterminada (o el archivo ya no existe), pide elegir uno
        y ofrece recordarlo para la proxima vez."""
        configured = self.settings_service.settings.default_no_aplica_template_path
        if configured and Path(configured).exists():
            return configured

        chosen, _ = QFileDialog.getOpenFileName(
            self, "Elegir PDF para las paginas 'NO APLICA'", "", "Archivos PDF (*.pdf)"
        )
        if not chosen:
            return None

        remember = QMessageBox.question(
            self,
            "Pagina 'NO APLICA'",
            "¿Usar este archivo como pagina 'NO APLICA' predeterminada para futuras secciones "
            "(en este proyecto y en los nuevos)?",
        )
        if remember == QMessageBox.Yes:
            self.settings_service.settings.default_no_aplica_template_path = chosen
            self.settings_service.save()
        return chosen

    def _on_no_aplica_toggled(self, checked: bool) -> None:
        section = self._current_section()
        if section is None:
            self.btn_no_aplica.blockSignals(True)
            self.btn_no_aplica.setChecked(False)
            self.btn_no_aplica.blockSignals(False)
            if checked:
                QMessageBox.information(self, "NO APLICA", "Seleccione primero una seccion.")
            return
        if checked:
            self._mark_section_no_aplica(section)
        else:
            self._unmark_section_no_aplica(section)

    def _mark_section_no_aplica(self, section: SectionNode) -> None:
        if any(d.is_no_aplica_placeholder for d in section.documents):
            return  # ya estaba marcada
        template_path = self._resolve_no_aplica_template_path()
        if not template_path:
            self._refresh_document_list()  # revierte el boton (el usuario cancelo la eleccion del PDF)
            return

        doc = DocumentItem(
            source_path=template_path,
            display_name="NO APLICA.pdf",
            signature_treatment=SignatureTreatment.KEEP_ORIGINAL,
            is_no_aplica_placeholder=True,
            order=len(section.documents),
        )
        self._inspect_document(doc)
        section.documents.append(doc)
        section_label = f"{section.numbering} {section.title}".strip()
        self._touch_project("Marcar 'No aplica'", f"Seccion '{section_label}'")
        self._refresh_ui()
        self.tree.select_section(section.id)

    def _unmark_section_no_aplica(self, section: SectionNode) -> None:
        if not any(d.is_no_aplica_placeholder for d in section.documents):
            return
        section.documents = [d for d in section.documents if not d.is_no_aplica_placeholder]
        for index, doc in enumerate(section.documents):
            doc.order = index
        section_label = f"{section.numbering} {section.title}".strip()
        self._touch_project("Quitar marca 'No aplica'", f"Seccion '{section_label}'")
        self._refresh_ui()
        self.tree.select_section(section.id)

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
        self._touch_project(
            "Eliminar seccion", f"'{label}' ({doc_count} documento(s), {child_count} subseccion(es))"
        )
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

        Inspeccionar cada PDF (abrirlo, contar paginas, detectar firmas)
        puede tardar un momento con archivos grandes o muchos a la vez; para
        que no parezca que el programa se congelo, se muestra un cursor de
        espera y un mensaje de progreso en la barra de estado (con varios
        documentos), procesando eventos de la interfaz entre uno y otro.
        """
        total = len(paths)
        show_progress = total > 2
        if show_progress:
            QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for index, path in enumerate(paths, start=1):
                if show_progress:
                    self.statusBar().showMessage(f"Agregando documentos... ({index}/{total})")
                    QApplication.processEvents()
                doc = DocumentItem(source_path=path, order=len(section.documents))
                self._inspect_document(doc)
                section.documents.append(doc)
        finally:
            if show_progress:
                QApplication.restoreOverrideCursor()
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
        section_label = f"{section.numbering} {section.title}".strip()
        self._touch_project("Agregar documentos", f"{len(paths)} documento(s) en '{section_label}'")
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
        section_label = f"{section.numbering} {section.title}".strip()
        self._touch_project(
            "Agregar documentos (carpeta)", f"{len(pdf_paths)} documento(s) desde '{folder}' en '{section_label}'"
        )
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
        section_label = f"{section.numbering} {section.title}".strip()
        self._touch_project("Agregar documentos (arrastrar y soltar)", f"{count} documento(s) en '{section_label}'")
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
        section_label = f"{section.numbering} {section.title}".strip()
        self._touch_project("Agregar documentos (arrastrar y soltar)", f"{count} documento(s) en '{section_label}'")
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

        self._touch_project("Distribuir documentos (auto)", f"{added_count} documento(s) distribuidos")
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
            self.btn_no_aplica.blockSignals(True)
            self.btn_no_aplica.setChecked(False)
            self.btn_no_aplica.blockSignals(False)
            return
        label = f"{section.numbering} {section.title}".strip()
        self.section_label.setText(f"{label}  ({len(section.documents)} documento(s))")
        self.doc_list.load_documents(section.documents)
        self.btn_no_aplica.blockSignals(True)
        self.btn_no_aplica.setChecked(any(d.is_no_aplica_placeholder for d in section.documents))
        self.btn_no_aplica.blockSignals(False)

    def _on_documents_reordered(self) -> None:
        section = self._current_section()
        if section is None:
            return
        by_id = {doc.id: doc for doc in section.documents}
        new_order = [by_id[doc_id] for doc_id in self.doc_list.ordered_document_ids() if doc_id in by_id]
        for index, doc in enumerate(new_order):
            doc.order = index
        section.documents = new_order
        section_label = f"{section.numbering} {section.title}".strip()
        self._touch_project("Reordenar documentos", f"Nuevo orden en '{section_label}'")
        self._refresh_thumbnail_rail()

    # ------------------------------------------------------------------
    # Panel de miniaturas (a la derecha): sincronizacion con seccion/documento
    # ------------------------------------------------------------------
    def _save_thumbnail_zoom(self) -> None:
        self.settings_service.settings.thumbnail_rail_zoom = self.thumbnail_zoom_slider.value()
        self.settings_service.save()

    def _find_document_and_section(self, document_id: str) -> tuple[Optional[SectionNode], Optional[DocumentItem]]:
        if not self.project:
            return None, None
        for section in self.project.iter_all_sections():
            for doc in section.documents:
                if doc.id == document_id:
                    return section, doc
        return None, None

    def _refresh_thumbnail_rail(self) -> None:
        """Reconstruye el panel de miniaturas con una imagen por cada HOJA
        del dossier completo, EN SU ORDEN REAL DE ENSAMBLADO: tanto las
        paginas de la plantilla (caratula, indice, separadores) como cada
        hoja de cada documento (un documento de varias paginas aparece como
        varias miniaturas consecutivas). Asi el total que se muestra aqui
        coincide con el del dossier final, y se puede ver el archivo
        completo, no solo los documentos agregados.

        El renderizado (abrir cada PDF y rasterizar cada pagina) se hace en
        un hilo aparte (``ThumbnailRailWorker``) para no congelar la
        interfaz: aqui solo se arma la lista de "que hay que renderizar"
        (rapido, sin abrir archivos de documentos) y se lanza el hilo.
        """
        specs = self._build_rail_specs()
        if not specs:
            self._cancel_thumbnail_worker()
            self.thumbnail_rail.clear()
            self._update_thumbnail_position_label()
            self._set_thumbnail_rail_busy(False)
            return

        self._cancel_thumbnail_worker()
        self._set_thumbnail_rail_busy(True)
        worker = ThumbnailRailWorker(specs, ThumbnailRailWidget.RENDER_WIDTH)
        worker.finished_ok.connect(self._on_thumbnail_worker_finished)
        self._thumbnail_worker = worker
        worker.start()

    def _cancel_thumbnail_worker(self) -> None:
        """Desconecta el resultado del hilo de miniaturas anterior (si
        seguia corriendo) para que, cuando termine, no pise con datos
        viejos lo que se muestra ahora. El hilo en si se deja terminar
        solo (forzar su interrupcion no es seguro en PySide6)."""
        if self._thumbnail_worker is not None:
            try:
                self._thumbnail_worker.finished_ok.disconnect(self._on_thumbnail_worker_finished)
            except (TypeError, RuntimeError):
                pass
            self._thumbnail_worker = None

    def _build_rail_specs(self) -> list[tuple]:
        """Arma, en el hilo principal, la lista de especificaciones (rutas,
        ids, textos) que el hilo de fondo va a renderizar. No abre ningun
        PDF de documento (solo lee datos ya en memoria del proyecto), asi
        que es practicamente instantaneo incluso con muchos documentos."""
        if not self.project or not self.project.template_path:
            return []
        try:
            builder = DossierBuilder(self.project)
            blocks = builder.build_blocks()
        except pdf_engine.PDFOpenError:
            return []

        section_labels = {
            section.id: f"{section.numbering} {section.title}".strip()
            for section in self.project.iter_all_sections()
        }

        specs: list[tuple] = []
        for block in blocks:
            kind = block[0]
            if kind == "template":
                _, page_index = block
                specs.append(("template", self.project.template_path, page_index))
            elif kind == "doc":
                _, section_id, doc = block
                specs.append(
                    (
                        "doc",
                        doc.id,
                        section_id,
                        section_labels.get(section_id, ""),
                        doc.name,
                        doc.source_path,
                        frozenset(doc.excluded_pages),
                    )
                )
            # los bloques "bookmark" (secciones dinamicas) no ocupan hoja fisica.
        return specs

    def _on_thumbnail_worker_finished(self, rendered: list[tuple]) -> None:
        entries = [
            RailEntry(
                document_id=document_id,
                section_id=section_id,
                page_index=page_index,
                caption=caption,
                pixmap=(QPixmap.fromImage(image) if image is not None else None),
                excluded=excluded,
            )
            for document_id, section_id, page_index, caption, image, excluded in rendered
        ]
        self.thumbnail_rail.load_entries(entries)
        self._update_thumbnail_position_label()
        self._thumbnail_worker = None
        self._set_thumbnail_rail_busy(False)

    def _set_thumbnail_rail_busy(self, busy: bool) -> None:
        self.thumbnail_busy_bar.setVisible(busy)

    def _on_thumbnail_current_changed(self, _current, _previous) -> None:
        self._update_thumbnail_position_label()

    def _update_thumbnail_position_label(self) -> None:
        """Indicador estilo Acrobat/Foxit: 'Hoja N de M' sobre el total de
        hojas del dossier completo, segun la miniatura actualmente
        seleccionada."""
        total = self.thumbnail_rail.count()
        if total == 0:
            self.thumbnail_position_label.setText("")
            return
        current_row = self.thumbnail_rail.currentRow()
        if current_row < 0:
            self.thumbnail_position_label.setText(f"{total} hoja(s) en total")
        else:
            self.thumbnail_position_label.setText(f"Hoja {current_row + 1} de {total}")

    def _on_thumbnail_activated(self, section_id: str, document_id: str, page_index: int) -> None:
        """Una miniatura fue seleccionada: llevar el arbol de secciones y la
        lista de documentos a esa misma seccion/documento (seleccion en
        cascada)."""
        if self._syncing_selection or self.project is None:
            return
        self._syncing_selection = True
        try:
            if section_id != self.current_section_id:
                self.tree.select_section(section_id)
            self.doc_list.select_document(document_id)
        finally:
            self._syncing_selection = False

    def _on_document_selection_changed(self) -> None:
        """Un documento fue seleccionado en la lista central: reflejar esa
        misma seleccion en el panel de miniaturas (en su primera hoja)."""
        if self._syncing_selection:
            return
        ids = self.doc_list.selected_document_ids()
        if len(ids) == 1 and self.current_section_id:
            self._syncing_selection = True
            try:
                self.thumbnail_rail.select_document(self.current_section_id, ids[0])
            finally:
                self._syncing_selection = False

    def _on_thumbnail_delete_requested(self) -> None:
        """Tecla Supr/Backspace sobre una miniatura: excluye esa hoja (o, si
        es la unica que queda, ofrece eliminar el documento completo)."""
        item = self.thumbnail_rail.currentItem()
        if item is None:
            return
        document_id = item.data(Qt.UserRole)
        page_index = item.data(Qt.UserRole + 2)
        if not document_id or page_index is None:
            return
        self._toggle_page_excluded(document_id, page_index, exclude=True)

    def _rail_page_count_for_document(self, document_id: str) -> int:
        """Cuenta cuantas hojas tiene ``document_id`` segun lo que el panel
        de miniaturas ya cargo (que abrio el PDF real), en vez de confiar en
        ``doc.page_count`` -- que puede no estar actualizado si el documento
        se agrego de una forma que no lo inspecciono (por ejemplo, al
        copiarlo a otra seccion) -- para no confundir "documento de 1 sola
        pagina" con "documento que todavia no registro su numero de
        paginas"."""
        count = sum(
            1
            for i in range(self.thumbnail_rail.count())
            if self.thumbnail_rail.item(i).data(Qt.UserRole) == document_id
        )
        return count or 1

    def _toggle_page_excluded(self, document_id: str, page_index: int, exclude: bool) -> None:
        section, doc = self._find_document_and_section(document_id)
        if doc is None:
            return
        excluded = set(doc.excluded_pages)

        if not exclude:
            excluded.discard(page_index)
            doc.excluded_pages = sorted(excluded)
            section_label = f"{section.numbering} {section.title}".strip() if section else ""
            self._touch_project(
                "Restaurar hoja", f"Hoja {page_index + 1} restaurada de '{doc.name}' en '{section_label}'"
            )
            self._refresh_thumbnail_rail()
            self._refresh_document_list()
            return

        if page_index in excluded:
            return  # ya estaba excluida: nada que hacer

        total_pages = self._rail_page_count_for_document(document_id)
        if (total_pages - len(excluded)) <= 1:
            confirm = QMessageBox.question(
                self,
                "Excluir hoja",
                "Esta es la unica hoja que queda de este documento. Para quitarla hay que "
                "eliminar el documento completo. Eliminarlo?",
            )
            if confirm == QMessageBox.Yes:
                self._syncing_selection = True
                try:
                    self.tree.select_section(section.id)
                    self.doc_list.select_document(document_id)
                finally:
                    self._syncing_selection = False
                self.remove_selected_documents()
            return

        confirm = QMessageBox.question(
            self,
            "Excluir hoja",
            f"Excluir la hoja {page_index + 1} de '{doc.name}' del dossier final?\n\n"
            "El archivo original no se modifica; la hoja se puede restaurar despues desde "
            "este mismo panel.",
        )
        if confirm != QMessageBox.Yes:
            return

        excluded.add(page_index)
        doc.excluded_pages = sorted(excluded)
        section_label = f"{section.numbering} {section.title}".strip() if section else ""
        self._touch_project("Excluir hoja", f"Hoja {page_index + 1} excluida de '{doc.name}' en '{section_label}'")
        self._refresh_thumbnail_rail()
        self._refresh_document_list()

    def _show_thumbnail_context_menu(self, pos) -> None:
        item = self.thumbnail_rail.itemAt(pos)
        if item is None:
            return
        if item is not self.thumbnail_rail.currentItem():
            self.thumbnail_rail.setCurrentItem(item)

        document_id = item.data(Qt.UserRole)
        page_index = item.data(Qt.UserRole + 2)

        menu = QMenu(self)
        if not document_id:
            action = menu.addAction("Pagina de la plantilla (no se puede modificar aqui)")
            action.setEnabled(False)
            menu.exec(self.thumbnail_rail.viewport().mapToGlobal(pos))
            return

        _section, doc = self._find_document_and_section(document_id)
        if doc is not None and self._rail_page_count_for_document(document_id) > 1:
            if page_index in set(doc.excluded_pages):
                menu.addAction(
                    "Restaurar esta hoja", lambda: self._toggle_page_excluded(document_id, page_index, exclude=False)
                )
            else:
                menu.addAction(
                    "Excluir esta hoja del dossier",
                    lambda: self._toggle_page_excluded(document_id, page_index, exclude=True),
                )
            menu.addSeparator()

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
        menu.addAction("+ Agregar documento(s) en esta seccion", self.add_documents)
        menu.addSeparator()
        menu.addAction("Eliminar documento completo", self.remove_selected_documents)

        menu.exec(self.thumbnail_rail.viewport().mapToGlobal(pos))

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
        moved_doc = section.documents[index]
        section.documents[index], section.documents[new_index] = (
            section.documents[new_index],
            section.documents[index],
        )
        for i, doc in enumerate(section.documents):
            doc.order = i
        section_label = f"{section.numbering} {section.title}".strip()
        verb = "Subir" if direction < 0 else "Bajar"
        self._touch_project(f"{verb} documento", f"'{moved_doc.name}' en '{section_label}'")
        self._refresh_document_list()
        self._refresh_thumbnail_rail()

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
        removed_names = [d.name for d in section.documents if d.id in selected_ids]
        section.documents = [d for d in section.documents if d.id not in selected_ids]
        for i, doc in enumerate(section.documents):
            doc.order = i
        section_label = f"{section.numbering} {section.title}".strip()
        self._touch_project(
            "Eliminar documentos", f"{', '.join(removed_names)} de '{section_label}'"
        )
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

        verb = "copiado(s)" if copy else "movido(s)"
        doc_names = ", ".join(d.name for d in selected_docs)
        source_label = f"{section.numbering} {section.title}".strip()
        self._touch_project(
            "Copiar documentos" if copy else "Mover documentos",
            f"{doc_names} de '{source_label}' a '{chosen_label}'",
        )
        self._refresh_ui()
        self.tree.select_section(target_id)
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

        treated_names = []
        for doc in section.documents:
            if doc.id in selected_ids:
                doc.signature_treatment = value
                treated_names.append(doc.name)
        treatment_labels = {
            SignatureTreatment.KEEP_ORIGINAL: "Conservar original",
            SignatureTreatment.FLATTEN: "Aplanar",
            SignatureTreatment.AUTO: "Automatico",
        }
        self._touch_project(
            "Cambiar tratamiento de firma",
            f"{', '.join(treated_names)} -> {treatment_labels.get(value, value.value)}",
        )
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
        old_title = section.title
        section.title = new_title.strip()
        self._touch_project("Renombrar seccion", f"'{old_title}' -> '{section.title}'")
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
        self._touch_project(
            "Generar dossier",
            f"Generacion N.° {result.generation_number}: {Path(result.output_pdf_path).name}",
        )

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
            self.btn_no_aplica,
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
            self.thumbnail_rail.clear()
            self.section_label.setText("Cree o abra un proyecto para comenzar")
            self.statusBar().clearMessage()
            return

        self.setWindowTitle(f"Dossier Builder QA/QC - {self.project.name}")
        self.tree.load_sections(self.project.sections)
        self._refresh_document_list()
        self._refresh_thumbnail_rail()

        total_docs = self.project.total_documents()
        signed_docs = sum(
            1 for s in self.project.iter_all_sections() for d in s.documents if d.has_signature
        )
        self.statusBar().showMessage(
            f"{total_docs} documento(s) | {signed_docs} con firma detectada | "
            f"plantilla: {Path(self.project.template_path).name if self.project.template_path else '-'}"
        )
