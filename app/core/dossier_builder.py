"""Orquestador de la generacion del dossier final.

Flujo (ver README): copiar plantilla -> aplanar documentos firmados que lo
requieran -> insertar todos los documentos en orden -> reconstruir bookmarks
-> aplicar metadatos -> optimizar -> guardar -> generar manifest y reporte.
"""
from __future__ import annotations

import getpass
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import fitz  # PyMuPDF

from app.core import bookmark_manager, pdf_engine
from app.core.flattener import FlattenError, FlattenOptions, flatten_pdf
from app.core.validator import Severity, ValidationReport, validate_project
from app.models.document_model import DocumentItem, DocumentStatus
from app.models.project_model import Project
from app.models.section_model import SectionNode
from app.services.logger import get_logger
from app.utils.hashing import sha256_file
from app.utils.naming import render_naming_pattern
from app.utils.paths import safe_filename

logger = get_logger("dossier_builder")

ProgressCallback = Callable[[int, int, str], None]
CancelCheck = Callable[[], bool]


class CancelledError(Exception):
    """La generacion fue cancelada por el usuario."""


class DossierGenerationError(Exception):
    """Error irrecuperable durante la generacion (no crashea la aplicacion)."""


@dataclass
class GenerationResult:
    output_pdf_path: str
    manifest_path: str
    report_path: str
    total_pages: int
    total_documents: int
    flattened_count: int
    sha256_final: str
    had_warnings: bool
    validation: ValidationReport = field(repr=False, default=None)


@dataclass
class PreviewRow:
    """Una fila de la vista previa estructural del dossier (sin abrir archivos)."""

    kind: str  # "template" | "doc"
    label: str
    section_label: str
    start_page: int  # 1-based, pagina estimada de inicio en el dossier final
    page_count: Optional[int]  # None si el documento aun no fue inspeccionado
    document_id: Optional[str] = None
    source_path: Optional[str] = None  # archivo de origen (plantilla o documento), para vista con miniaturas
    source_page_index: int = 0  # pagina 0-based dentro de source_path a renderizar como miniatura


# -- Indice automatico (opcional) --------------------------------------
#
# La paginacion (cuantas paginas de indice se necesitan) depende solo de
# CUANTAS entradas hay, no del VALOR de los numeros de pagina que se van a
# imprimir (cada entrada ocupa siempre una linea de alto fijo). Eso permite
# resolver la referencia circular "el indice necesita saber los numeros de
# pagina finales, pero insertarlo cambia esos numeros": primero se calcula
# cuantas paginas de indice va a haber (_estimate_index_page_count, a partir
# de la cantidad de entradas), luego se suman esas paginas como offset a las
# posiciones ya calculadas del ensamblado normal, y recien con esos numeros
# ya definitivos se dibuja el indice (_render_index_document).
_INDEX_PAGE_WIDTH = 595.0
_INDEX_PAGE_HEIGHT = 842.0
_INDEX_MARGIN_TOP = 70.0
_INDEX_MARGIN_BOTTOM = 50.0
_INDEX_LINE_HEIGHT = 16.0
_INDEX_TITLE_HEIGHT = 30.0
_INDEX_FONT_SIZE = 10
_INDEX_RIGHT_MARGIN = 60.0


def _index_lines_capacity(is_first_page: bool) -> int:
    usable = _INDEX_PAGE_HEIGHT - _INDEX_MARGIN_TOP - _INDEX_MARGIN_BOTTOM
    if is_first_page:
        usable -= _INDEX_TITLE_HEIGHT
    # +1: la primera entrada de la pagina se dibuja en la posicion inicial
    # (sin haber "gastado" todavia una altura de linea), asi que en el mismo
    # espacio disponible entra una entrada mas de las que da la division
    # entera pura. Debe coincidir exactamente con el bucle de dibujo en
    # _render_index_document (mismo umbral "y > limite").
    return max(1, int(usable // _INDEX_LINE_HEIGHT) + 1)


def _estimate_index_page_count(entry_count: int) -> int:
    if entry_count <= 0:
        return 1
    pages = 0
    remaining = entry_count
    while remaining > 0:
        remaining -= _index_lines_capacity(is_first_page=(pages == 0))
        pages += 1
    return pages


def _render_index_document(entries: list[tuple[int, str, int]]) -> fitz.Document:
    """``entries`` = (nivel, titulo, pagina final 1-based) ya con el offset
    del indice aplicado. Dibuja "CONTENIDO" + una linea por entrada, con
    lider de puntos hasta el numero de pagina alineado a la derecha.
    """
    doc = fitz.open()
    page = None
    page_index = -1
    y = 0.0

    for level, title, page_number in entries:
        if page is None or y > _INDEX_PAGE_HEIGHT - _INDEX_MARGIN_BOTTOM:
            page = doc.new_page(width=_INDEX_PAGE_WIDTH, height=_INDEX_PAGE_HEIGHT)
            page_index += 1
            y = _INDEX_MARGIN_TOP
            if page_index == 0:
                page.insert_text((50, y), "CONTENIDO", fontsize=16)
                y += _INDEX_TITLE_HEIGHT

        indent = 50 + (max(1, level) - 1) * 16
        fontsize = _INDEX_FONT_SIZE + (1 if level == 1 else 0)
        page.insert_text((indent, y), title, fontsize=fontsize)

        page_str = str(page_number)
        number_width = fitz.get_text_length(page_str, fontsize=fontsize)
        number_x = _INDEX_PAGE_WIDTH - _INDEX_RIGHT_MARGIN - number_width
        title_width = fitz.get_text_length(title, fontsize=fontsize)
        dots_start_x = indent + title_width + 4
        if number_x - 4 > dots_start_x:
            dot_width = fitz.get_text_length(".", fontsize=fontsize) or 3
            num_dots = max(0, int((number_x - 4 - dots_start_x) / dot_width))
            page.insert_text((dots_start_x, y), "." * num_dots, fontsize=fontsize, color=(0.6, 0.6, 0.6))
        page.insert_text((number_x, y), page_str, fontsize=fontsize)

        y += _INDEX_LINE_HEIGHT

    if page is None:
        doc.new_page(width=_INDEX_PAGE_WIDTH, height=_INDEX_PAGE_HEIGHT)

    return doc


# Cada cuantas inserciones (paginas de plantilla o documentos) se guarda y
# reabre el documento en construccion. PyMuPDF puede degradar su estado
# interno (cache de objetos/graft map) tras MUCHAS llamadas a insert_pdf()
# seguidas sobre el mismo documento que va creciendo, lo que en dossiers con
# muchos documentos puede terminar en un error de bajo nivel como "source
# object number out of range". Guardar y reabrir periodicamente resetea ese
# estado interno y evita el problema, a cambio de un poco de E/S extra.
_FLUSH_EVERY_N_INSERTS = 15


def _noop_progress(current: int, total: int, message: str) -> None:  # pragma: no cover - trivial
    pass


class DossierBuilder:
    """Genera el PDF final de un :class:`Project` ya validado."""

    def __init__(self, project: Project):
        self.project = project

    # ------------------------------------------------------------------
    def generate(
        self,
        output_root: str,
        output_filename: Optional[str] = None,
        progress_cb: Optional[ProgressCallback] = None,
        cancel_check: Optional[CancelCheck] = None,
    ) -> GenerationResult:
        """``output_filename``, si se da, reemplaza el nombre calculado con
        ``settings.output_naming_pattern`` (sin necesidad de incluir la
        extension ``.pdf``, se agrega sola)."""
        progress_cb = progress_cb or _noop_progress
        cancel_check = cancel_check or (lambda: False)

        validation = validate_project(self.project)
        if not validation.can_generate:
            raise DossierGenerationError(
                "No se puede generar el dossier: existen errores criticos. "
                "Ejecute 'Validar dossier' para verlos."
            )

        template_path = Path(self.project.template_path)
        template_page_count = pdf_engine.get_page_count(str(template_path))

        dirs = self._prepare_output_dirs(output_root)

        all_docs = list(self._iter_all_documents())
        # Cada documento se cuenta dos veces (preparacion/aplanado + insercion
        # en el ensamblado), mas una tick por cada pagina de plantilla copiada,
        # 3 ticks finales (bookmarks, guardado, reporte) y 1 mas si se genera
        # el indice automatico.
        total_steps = 2 * len(all_docs) + template_page_count + 3
        if self.project.settings.generate_automatic_index:
            total_steps += 1
        step = 0

        def tick(message: str) -> None:
            nonlocal step
            step += 1
            progress_cb(step, total_steps, message)
            if cancel_check():
                raise CancelledError("Generacion cancelada por el usuario.")

        # -- 1. Preparar (backup + aplanado) de documentos firmados --------
        flattened_count = 0
        for section, doc in all_docs:
            self._prepare_document(doc, dirs)
            if doc.status == DocumentStatus.FLATTENED:
                flattened_count += 1
            tick(f"Procesando: {doc.name}")

        # -- 2. Ensamblar el PDF final --------------------------------------
        section_page_position: dict[str, int] = {}
        document_page_position: dict[str, int] = {}

        # Cada pagina de la plantilla se extrae de antemano a su propio
        # documento PyMuPDF de una sola pagina, en vez de reutilizar el mismo
        # `template_doc` abierto para copiar paginas una por una intercaladas
        # con la insercion de los demas documentos. Reutilizar el mismo
        # documento de origen para muchas llamadas a insert_pdf() separadas,
        # intercaladas con inserciones desde OTROS documentos que van
        # haciendo crecer out_doc, puede hacer que PyMuPDF falle con
        # "source object number out of range" (problema conocido de la
        # libreria con el "graft map" cuando se reutiliza el mismo origen
        # despues de que el destino cambio por otras inserciones). Al usar
        # un documento de origen distinto y de un solo uso por cada pagina,
        # ese problema no puede ocurrir.
        template_doc = pdf_engine.open_document(str(template_path))
        try:
            template_page_docs: dict[int, fitz.Document] = {}
            try:
                for page_index in range(template_page_count):
                    single_page_doc = fitz.open()
                    single_page_doc.insert_pdf(template_doc, from_page=page_index, to_page=page_index)
                    template_page_docs[page_index] = single_page_doc
            except Exception as exc:  # noqa: BLE001 - error de bajo nivel de PyMuPDF
                for doc in template_page_docs.values():
                    doc.close()
                raise DossierGenerationError(
                    f"No se pudo leer la pagina {page_index + 1} de la plantilla: {exc}"
                ) from exc
        finally:
            template_doc.close()

        out_doc = pdf_engine.new_empty_document()
        physical_section_by_page: dict[int, str] = {
            node.template_page_index: node.id
            for node in self.project.iter_all_sections()
            if node.template_page_index is not None
        }
        flush_temp_paths: list[str] = []
        inserts_since_flush = 0

        def flush_out_doc() -> None:
            """Guarda el documento en construccion a un archivo temporal y lo
            reabre, para resetear el estado interno de PyMuPDF (ver
            _FLUSH_EVERY_N_INSERTS mas arriba)."""
            nonlocal out_doc, inserts_since_flush
            fd, temp_path = tempfile.mkstemp(suffix=".pdf")
            os.close(fd)
            out_doc.save(temp_path)
            out_doc.close()
            flush_temp_paths.append(temp_path)
            out_doc = fitz.open(temp_path)
            inserts_since_flush = 0

        try:
            blocks = self._build_blocks(template_page_count)
            for block in blocks:
                kind = block[0]
                if kind == "template":
                    _, page_index = block
                    try:
                        out_doc.insert_pdf(template_page_docs[page_index], start_at=out_doc.page_count)
                    except Exception as exc:  # noqa: BLE001 - error de bajo nivel de PyMuPDF
                        raise DossierGenerationError(
                            f"No se pudo insertar la pagina {page_index + 1} de la plantilla en el dossier: {exc}"
                        ) from exc
                    inserts_since_flush += 1
                    # La pagina separadora fisica que acabamos de copiar ES la
                    # posicion del bookmark de su seccion (no un marcador aparte,
                    # para no contarla dos veces).
                    owner_section_id = physical_section_by_page.get(page_index)
                    if owner_section_id is not None:
                        section_page_position.setdefault(owner_section_id, out_doc.page_count - 1)
                    tick(f"Copiando pagina de plantilla {page_index + 1}/{template_page_count}")
                elif kind == "bookmark":
                    _, section_id = block
                    section_page_position.setdefault(section_id, out_doc.page_count)
                elif kind == "doc":
                    _, section_id, doc = block
                    section_page_position.setdefault(section_id, out_doc.page_count)
                    insert_path = doc.flattened_path or doc.source_path
                    first_page = out_doc.page_count
                    try:
                        pdf_engine.insert_pdf_pages(out_doc, insert_path, out_doc.page_count)
                    except Exception as exc:  # noqa: BLE001 - incluye errores de bajo nivel de PyMuPDF
                        raise DossierGenerationError(
                            f"No se pudo insertar '{doc.name}' en el dossier: {exc}. Ruta: {insert_path}"
                        ) from exc
                    inserts_since_flush += 1
                    document_page_position[doc.id] = first_page
                    tick(f"Insertando: {doc.name}")

                if inserts_since_flush >= _FLUSH_EVERY_N_INSERTS:
                    flush_out_doc()

            # -- 2b. Indice automatico (opcional) -------------------------------
            index_inserted = False
            if self.project.settings.generate_automatic_index:
                inserted_pages = self._insert_automatic_index(out_doc, section_page_position, document_page_position)
                index_inserted = inserted_pages > 0
                tick("Generando indice automatico")

            # -- 3. Bookmarks -------------------------------------------------
            toc = bookmark_manager.build_toc_for_document(
                self.project.sections,
                section_page_position,
                document_page_position,
                create_document_bookmarks=self.project.settings.create_bookmarks_for_individual_docs,
            )
            if index_inserted:
                toc.insert(0, [1, "INDICE", 1])
            pdf_engine.set_toc(out_doc, toc)
            tick("Reconstruyendo bookmarks")

            # -- 4. Metadatos ---------------------------------------------------
            pdf_engine.set_metadata(out_doc, self._build_pdf_metadata())

            # -- 5. Guardar -------------------------------------------------------
            if output_filename and output_filename.strip():
                output_name = safe_filename(Path(output_filename.strip()).stem)
            else:
                output_name = render_naming_pattern(
                    self.project.settings.output_naming_pattern, self.project.metadata.as_naming_context()
                )
            output_path = dirs["final"] / f"{output_name}.pdf"
            pdf_engine.save_document(out_doc, str(output_path), optimize=True)
            tick("Guardando dossier final")
        finally:
            for single_page_doc in template_page_docs.values():
                single_page_doc.close()
            out_doc.close()
            for temp_path in flush_temp_paths:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except OSError:
                    logger.warning("No se pudo borrar el archivo temporal '%s'", temp_path)

        # -- 5b. Renombrar originales firmados con su pagina de inicio -------
        # Recien aqui se conoce con certeza la pagina final de cada
        # documento (el ensamblado, incluido el indice automatico si
        # aplica, ya termino), asi que el renombrado se hace al final.
        self._rename_signed_originals_with_page_numbers(all_docs, document_page_position)

        # -- 6. Manifest + reporte ------------------------------------------
        sha_final = sha256_file(output_path)
        final_page_count = pdf_engine.get_page_count(str(output_path))

        manifest_path = dirs["reports"] / "manifest.json"
        self._write_manifest(
            manifest_path, output_path, sha_final, final_page_count, flattened_count, validation, document_page_position
        )

        report_path = dirs["reports"] / "Reporte_Generacion.pdf"
        self._write_report_pdf(
            report_path,
            output_path,
            sha_final,
            final_page_count,
            len(all_docs),
            flattened_count,
            validation,
            document_page_position,
        )
        tick("Reporte generado")

        logger.info(
            "Dossier generado: %s (%d paginas, %d documentos, %d aplanados)",
            output_path,
            final_page_count,
            len(all_docs),
            flattened_count,
        )

        return GenerationResult(
            output_pdf_path=str(output_path),
            manifest_path=str(manifest_path),
            report_path=str(report_path),
            total_pages=final_page_count,
            total_documents=len(all_docs),
            flattened_count=flattened_count,
            sha256_final=sha_final,
            had_warnings=bool(validation.warnings),
            validation=validation,
        )

    # ------------------------------------------------------------------
    def _insert_automatic_index(
        self,
        out_doc: fitz.Document,
        section_page_position: dict[str, int],
        document_page_position: dict[str, int],
    ) -> int:
        """Genera paginas de indice (seccion/subseccion + pagina) y las
        inserta al comienzo de ``out_doc``, desplazando las posiciones ya
        calculadas de secciones y documentos. Devuelve la cantidad de
        paginas de indice insertadas.

        Si ``settings.include_documents_in_index`` esta activo, cada
        documento original tambien aparece en el indice, anidado bajo su
        seccion, con su nombre y la pagina donde empieza dentro del dossier
        final (ej. "pag. 185  NOMBRE_ARCHIVO.pdf") — util para ubicar
        rapidamente un documento original dentro del PDF completo.
        """
        include_docs = self.project.settings.include_documents_in_index
        # (nivel, titulo, kind, ref_id): kind="section" -> ref_id busca en
        # section_page_position; kind="doc" -> ref_id busca en document_page_position.
        entries: list[tuple[int, str, str, str]] = []

        def walk(nodes: list[SectionNode]) -> None:
            for node in sorted(nodes, key=lambda n: n.order):
                if node.create_bookmark and node.id in section_page_position:
                    title = f"{node.numbering} {node.title}".strip() if node.numbering else node.title
                    entries.append((node.level, title, "section", node.id))
                    if include_docs:
                        for doc in node.documents:
                            if doc.id in document_page_position:
                                entries.append((node.level + 1, doc.name, "doc", doc.id))
                walk(node.children)

        walk(self.project.sections)

        if not entries:
            return 0

        index_page_count = _estimate_index_page_count(len(entries))
        position_by_kind = {"section": section_page_position, "doc": document_page_position}

        def render_with_offset(offset: int) -> fitz.Document:
            rendered = [
                (level, title, position_by_kind[kind][ref_id] + 1 + offset) for level, title, kind, ref_id in entries
            ]
            return _render_index_document(rendered)

        index_doc = render_with_offset(index_page_count)
        if index_doc.page_count != index_page_count:
            # Salvaguarda: si la estimacion no coincidio con lo realmente
            # dibujado (por ejemplo por un cambio futuro en el layout sin
            # actualizar _estimate_index_page_count), se re-renderiza una
            # vez mas ya con el numero real de paginas.
            index_page_count = index_doc.page_count
            index_doc.close()
            index_doc = render_with_offset(index_page_count)

        try:
            out_doc.insert_pdf(index_doc, start_at=0)
        except Exception as exc:  # noqa: BLE001 - incluye errores de bajo nivel de PyMuPDF
            index_doc.close()
            raise DossierGenerationError(f"No se pudo insertar el indice automatico en el dossier: {exc}") from exc
        index_doc.close()

        for key in list(section_page_position):
            section_page_position[key] += index_page_count
        for key in list(document_page_position):
            document_page_position[key] += index_page_count

        return index_page_count

    # ------------------------------------------------------------------
    def build_preview_outline(self, template_page_count: Optional[int] = None) -> list[PreviewRow]:
        """Vista previa estructural y rapida del dossier: el orden final de
        paginas de plantilla y documentos, SIN abrir ni aplanar ningun PDF
        (usa el ``page_count`` ya detectado al agregar cada documento). Sirve
        para revisar el orden antes de generar, incluso en dossiers de
        cientos de paginas, sin el costo de renderizar miniaturas.
        """
        if template_page_count is None:
            template_page_count = self.project.template_page_count
        if template_page_count is None and self.project.template_path:
            template_page_count = pdf_engine.get_page_count(self.project.template_path)
        template_page_count = template_page_count or 0

        section_labels = {
            node.id: f"{node.numbering} {node.title}".strip() for node in self.project.iter_all_sections()
        }

        blocks = self._build_blocks(template_page_count)
        rows: list[PreviewRow] = []
        running_page = 1
        for block in blocks:
            kind = block[0]
            if kind == "template":
                _, page_index = block
                rows.append(
                    PreviewRow(
                        kind="template",
                        label=f"Pagina de plantilla {page_index + 1}",
                        section_label="",
                        start_page=running_page,
                        page_count=1,
                        source_path=self.project.template_path or None,
                        source_page_index=page_index,
                    )
                )
                running_page += 1
            elif kind == "doc":
                _, section_id, doc = block
                pages = doc.page_count
                rows.append(
                    PreviewRow(
                        kind="doc",
                        label=doc.name,
                        section_label=section_labels.get(section_id, ""),
                        start_page=running_page,
                        page_count=pages,
                        document_id=doc.id,
                        source_path=doc.flattened_path or doc.source_path or None,
                        source_page_index=0,
                    )
                )
                running_page += pages if pages else 1
            # los marcadores "bookmark" (secciones dinamicas) no ocupan pagina.
        return rows

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _iter_all_documents(self):
        for section in self.project.iter_all_sections():
            for doc in section.documents:
                yield section, doc

    def _prepare_output_dirs(self, output_root: str) -> dict[str, Path]:
        root = Path(output_root) / safe_filename(self.project.name)
        dirs = {
            "root": root,
            "backup": root / "00_ORIGINALES_FIRMADOS",
            "processed": root / "01_DOCUMENTOS_PROCESADOS",
            "final": root / "02_DOSSIER_FINAL",
            "reports": root / "03_REPORTES",
        }
        for path in dirs.values():
            path.mkdir(parents=True, exist_ok=True)
        return dirs

    def _prepare_document(self, doc: DocumentItem, dirs: dict[str, Path]) -> None:
        source = Path(doc.source_path)
        doc.file_size_bytes = source.stat().st_size
        doc.sha256_original = sha256_file(source)
        try:
            doc.page_count = pdf_engine.get_page_count(str(source))
        except pdf_engine.PDFOpenError as exc:
            doc.status = DocumentStatus.ERROR
            doc.error_message = str(exc)
            raise DossierGenerationError(str(exc)) from exc

        if not doc.will_be_flattened:
            doc.status = DocumentStatus.OK
            return

        if self.project.settings.keep_backup_of_signed_originals:
            backup_path = dirs["backup"] / f"{safe_filename(doc.name)}"
            if not backup_path.exists():
                shutil.copy2(source, backup_path)
            doc.backup_path = str(backup_path)

        flat_name = f"{safe_filename(Path(doc.name).stem)}__flat.pdf"
        flat_path = dirs["processed"] / flat_name
        try:
            flatten_pdf(
                str(source),
                str(flat_path),
                FlattenOptions(
                    dpi=self.project.settings.flatten_dpi,
                    image_format=self.project.settings.flatten_image_format,
                ),
            )
        except FlattenError as exc:
            doc.status = DocumentStatus.ERROR
            doc.error_message = str(exc)
            raise DossierGenerationError(str(exc)) from exc

        doc.flattened_path = str(flat_path)
        doc.flatten_dpi = self.project.settings.flatten_dpi
        doc.sha256_flattened = sha256_file(flat_path)
        doc.status = DocumentStatus.FLATTENED

    def _rename_signed_originals_with_page_numbers(
        self,
        all_docs: list[tuple[SectionNode, DocumentItem]],
        document_page_position: dict[str, int],
    ) -> None:
        """Renombra la copia de respaldo (00_ORIGINALES_FIRMADOS/) y la
        version aplanada (01_DOCUMENTOS_PROCESADOS/) de cada documento con
        firma, anteponiendo la pagina donde termino en el dossier final:
        ``pag {N}_{nombre_original}.pdf``. Solo puede hacerse aqui, una vez
        terminado el ensamblado (incluido el indice automatico si aplica),
        que es cuando se conoce la pagina real de cada documento.
        """
        for _section, doc in all_docs:
            start_page = document_page_position.get(doc.id)
            if start_page is None:
                continue
            page_number = start_page + 1

            if doc.backup_path:
                doc.backup_path = self._rename_with_page_prefix(doc.backup_path, page_number)
            if doc.flattened_path:
                doc.flattened_path = self._rename_with_page_prefix(doc.flattened_path, page_number)

    def _rename_with_page_prefix(self, path_str: str, page_number: int) -> str:
        path = Path(path_str)
        if not path.exists():
            return path_str
        new_name = safe_filename(f"pag {page_number}_{path.name}")
        if new_name == path.name:
            return path_str
        new_path = path.with_name(new_name)
        try:
            path.rename(new_path)
            return str(new_path)
        except OSError as exc:
            logger.warning("No se pudo renombrar '%s' con su pagina de inicio: %s", path, exc)
            return path_str

    def _build_blocks(self, template_page_count: int) -> list[tuple]:
        """Construye la secuencia ordenada de bloques (paginas de plantilla,
        marcadores de bookmark y documentos) que conforman el dossier final.
        """
        anchors: dict[int, list[tuple]] = {}

        def collect(section: SectionNode, is_anchor_owner: bool) -> list[tuple]:
            # La seccion "dueña" de un ancla fisica (la que tiene la pagina
            # separadora) obtiene su posicion de bookmark directamente al
            # copiar esa pagina de plantilla (ver bucle de ensamblado), asi
            # que aqui NO se emite un marcador para ella (evitaria contarla
            # una pagina de mas). Las secciones dinamicas (sin pagina propia)
            # si necesitan su propio marcador.
            items: list[tuple] = [] if is_anchor_owner else [("bookmark", section.id)]
            for doc in section.documents:
                items.append(("doc", section.id, doc))
            for child in sorted(section.children, key=lambda n: n.order):
                if child.template_page_index is None:
                    items.extend(collect(child, is_anchor_owner=False))
            return items

        for node in self.project.iter_all_sections():
            if node.template_page_index is not None:
                anchors.setdefault(node.template_page_index, []).extend(collect(node, is_anchor_owner=True))

        for root in self.project.sections:
            if root.template_page_index is None:
                anchors.setdefault(template_page_count, []).extend(collect(root, is_anchor_owner=False))

        blocks: list[tuple] = []
        for page_index in range(template_page_count):
            blocks.append(("template", page_index))
            blocks.extend(anchors.get(page_index, []))
        blocks.extend(anchors.get(template_page_count, []))
        return blocks

    def _build_pdf_metadata(self) -> dict[str, str]:
        meta = self.project.metadata
        return {
            "title": meta.titulo_pdf or self.project.name,
            "author": meta.autor_pdf,
            "subject": meta.asunto_pdf,
            "keywords": meta.keywords_pdf,
            "producer": "Dossier Builder QA/QC",
        }

    def _write_manifest(
        self,
        manifest_path: Path,
        output_path: Path,
        sha_final: str,
        final_page_count: int,
        flattened_count: int,
        validation: ValidationReport,
        document_page_position: dict[str, int],
    ) -> None:
        documents = []
        for section, doc in self._iter_all_documents():
            start_page = document_page_position.get(doc.id)
            documents.append(
                {
                    "section": f"{section.numbering} {section.title}".strip(),
                    "name": doc.name,
                    "start_page": (start_page + 1) if start_page is not None else None,
                    "source_path": doc.source_path,
                    "sha256_original": doc.sha256_original,
                    "flattened": doc.will_be_flattened,
                    "flattened_path": doc.flattened_path,
                    "backup_path": doc.backup_path,
                    "sha256_flattened": doc.sha256_flattened,
                    "flatten_dpi": doc.flatten_dpi,
                    "has_signature": doc.has_signature,
                    "page_count": doc.page_count,
                }
            )

        manifest = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "generated_by": getpass.getuser(),
            "project_name": self.project.name,
            "project_id": self.project.id,
            "template_path": self.project.template_path,
            "metadata": self.project.metadata.to_dict(),
            "output_pdf": {"path": str(output_path), "sha256": sha_final, "page_count": final_page_count},
            "total_documents": len(documents),
            "flattened_count": flattened_count,
            "documents": documents,
            "warnings": [m.message for m in validation.warnings],
            "errors": [m.message for m in validation.errors],
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    def _write_report_pdf(
        self,
        report_path: Path,
        output_path: Path,
        sha_final: str,
        final_page_count: int,
        total_documents: int,
        flattened_count: int,
        validation: ValidationReport,
        document_page_position: dict[str, int],
    ) -> None:
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)  # A4
        text_lines = [
            "REPORTE DE GENERACION - DOSSIER BUILDER QA/QC",
            "",
            f"Proyecto: {self.project.name}",
            f"Archivo generado: {output_path.name}",
            f"Fecha/hora: {datetime.now(timezone.utc).isoformat(timespec='seconds')} UTC",
            f"Usuario: {getpass.getuser()}",
            f"Plantilla utilizada: {self.project.template_path}",
            "",
            f"Total de paginas: {final_page_count}",
            f"Total de documentos insertados: {total_documents}",
            f"Documentos aplanados (firma): {flattened_count}",
            f"SHA-256 del dossier final: {sha_final}",
            "",
            f"Advertencias: {len(validation.warnings)}",
            f"Errores: {len(validation.errors)}",
            "",
            "Secciones:",
        ]
        for section in self.project.iter_all_sections():
            text_lines.append(
                f"  {section.numbering} {section.title} - {len(section.documents)} documento(s)"
            )

        # Documentos originales con su pagina de inicio dentro del dossier
        # final (util para ubicar rapidamente un documento en el PDF
        # completo), ordenados por orden de aparicion en el dossier.
        doc_rows = []
        for section, item in self._iter_all_documents():
            start_page = document_page_position.get(item.id)
            if start_page is not None:
                doc_rows.append((start_page, item.name))
        doc_rows.sort(key=lambda row: row[0])

        if doc_rows:
            text_lines.append("")
            text_lines.append("Documentos originales (pagina de inicio en el dossier final):")
            for start_page, name in doc_rows:
                text_lines.append(f"  pag. {start_page + 1}  {name}")

        if validation.warnings:
            text_lines.append("")
            text_lines.append("Detalle de advertencias:")
            for msg in validation.warnings:
                text_lines.append(f"  - {msg.message}")

        y = 40
        for line in text_lines:
            if y > 800:
                page = doc.new_page(width=595, height=842)
                y = 40
            page.insert_text((40, y), line, fontsize=10)
            y += 14

        doc.save(str(report_path))
        doc.close()
