"""Orquestador de la generacion del dossier final.

Flujo (ver README): copiar plantilla -> aplanar documentos firmados que lo
requieran -> insertar todos los documentos en orden -> reconstruir bookmarks
-> aplicar metadatos -> optimizar -> guardar -> generar manifest y reporte.
"""
from __future__ import annotations

import getpass
import json
import shutil
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
        progress_cb: Optional[ProgressCallback] = None,
        cancel_check: Optional[CancelCheck] = None,
    ) -> GenerationResult:
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
        # en el ensamblado), mas una tick por cada pagina de plantilla copiada
        # y 3 ticks finales (bookmarks, guardado, reporte).
        total_steps = 2 * len(all_docs) + template_page_count + 3
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

        template_doc = pdf_engine.open_document(str(template_path))
        out_doc = pdf_engine.new_empty_document()
        physical_section_by_page: dict[int, str] = {
            node.template_page_index: node.id
            for node in self.project.iter_all_sections()
            if node.template_page_index is not None
        }
        try:
            blocks = self._build_blocks(template_page_count)
            for block in blocks:
                kind = block[0]
                if kind == "template":
                    _, page_index = block
                    out_doc.insert_pdf(template_doc, from_page=page_index, to_page=page_index, start_at=out_doc.page_count)
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
                    except pdf_engine.PDFOpenError as exc:
                        raise DossierGenerationError(
                            f"No se pudo insertar '{doc.name}' en el dossier: {exc}"
                        ) from exc
                    document_page_position[doc.id] = first_page
                    tick(f"Insertando: {doc.name}")

            # -- 3. Bookmarks -------------------------------------------------
            toc = bookmark_manager.build_toc_for_document(
                self.project.sections,
                section_page_position,
                document_page_position,
                create_document_bookmarks=self.project.settings.create_bookmarks_for_individual_docs,
            )
            pdf_engine.set_toc(out_doc, toc)
            tick("Reconstruyendo bookmarks")

            # -- 4. Metadatos ---------------------------------------------------
            pdf_engine.set_metadata(out_doc, self._build_pdf_metadata())

            # -- 5. Guardar -------------------------------------------------------
            output_name = render_naming_pattern(
                self.project.settings.output_naming_pattern, self.project.metadata.as_naming_context()
            )
            output_path = dirs["final"] / f"{output_name}.pdf"
            pdf_engine.save_document(out_doc, str(output_path), optimize=True)
            tick("Guardando dossier final")
        finally:
            template_doc.close()
            out_doc.close()

        # -- 6. Manifest + reporte ------------------------------------------
        sha_final = sha256_file(output_path)
        final_page_count = pdf_engine.get_page_count(str(output_path))

        manifest_path = dirs["reports"] / "manifest.json"
        self._write_manifest(manifest_path, output_path, sha_final, final_page_count, flattened_count, validation)

        report_path = dirs["reports"] / "Reporte_Generacion.pdf"
        self._write_report_pdf(
            report_path, output_path, sha_final, final_page_count, len(all_docs), flattened_count, validation
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
    ) -> None:
        documents = []
        for section, doc in self._iter_all_documents():
            documents.append(
                {
                    "section": f"{section.numbering} {section.title}".strip(),
                    "name": doc.name,
                    "source_path": doc.source_path,
                    "sha256_original": doc.sha256_original,
                    "flattened": doc.will_be_flattened,
                    "flattened_path": doc.flattened_path,
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
