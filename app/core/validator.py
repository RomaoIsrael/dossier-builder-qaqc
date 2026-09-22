"""Validacion previa de un proyecto antes de generar el dossier final."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from app.core import pdf_engine
from app.models.project_model import Project
from app.models.section_model import SectionNode
from app.services.logger import get_logger

logger = get_logger("validator")


class Severity(str, Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class ValidationMessage:
    severity: Severity
    message: str
    target: str = ""  # seccion/documento al que se refiere, para navegacion en la UI


@dataclass
class ValidationReport:
    messages: list[ValidationMessage] = field(default_factory=list)

    def add(self, severity: Severity, message: str, target: str = "") -> None:
        self.messages.append(ValidationMessage(severity, message, target))
        logger.log(
            {"ok": 20, "warning": 30, "error": 40}[severity.value],
            "[%s] %s (%s)",
            severity.value.upper(),
            message,
            target,
        )

    @property
    def errors(self) -> list[ValidationMessage]:
        return [m for m in self.messages if m.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationMessage]:
        return [m for m in self.messages if m.severity == Severity.WARNING]

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def can_generate(self) -> bool:
        return not self.has_errors


def validate_project(project: Project) -> ValidationReport:
    report = ValidationReport()

    # -- Plantilla -----------------------------------------------------
    if not project.template_path:
        report.add(Severity.ERROR, "No se ha cargado una plantilla de dossier.", "plantilla")
        return report  # sin plantilla no tiene sentido seguir validando

    template_path = Path(project.template_path)
    if not template_path.exists():
        report.add(Severity.ERROR, f"La plantilla no se encuentra en disco: {template_path}", "plantilla")
        return report

    ok, err = pdf_engine.is_pdf_readable(str(template_path))
    if not ok:
        report.add(Severity.ERROR, f"La plantilla no se pudo leer: {err}", "plantilla")
        return report
    report.add(Severity.OK, "Plantilla cargada correctamente.", "plantilla")

    if not project.sections:
        report.add(Severity.ERROR, "La plantilla no tiene secciones/bookmarks definidos.", "plantilla")
        return report

    # -- Recorrido de secciones -----------------------------------------
    seen_names: dict[str, list[str]] = {}
    total_docs = 0

    def walk(nodes: list[SectionNode]) -> None:
        nonlocal total_docs
        for node in nodes:
            label = f"{node.numbering} {node.title}".strip()

            if not node.documents and not node.children:
                report.add(Severity.WARNING, f"La seccion '{label}' esta vacia (sin documentos).", node.id)
            elif node.documents:
                report.add(
                    Severity.OK,
                    f"'{label}' contiene {len(node.documents)} documento(s).",
                    node.id,
                )

            for doc in node.documents:
                total_docs += 1
                _validate_document(report, doc, label)
                seen_names.setdefault(doc.name.lower(), []).append(label)

            walk(node.children)

    walk(project.sections)

    for name, locations in seen_names.items():
        if len(locations) > 1:
            report.add(
                Severity.WARNING,
                f"El nombre de archivo '{name}' aparece {len(locations)} veces en el dossier "
                f"({', '.join(locations)}).",
                name,
            )

    if total_docs == 0:
        report.add(Severity.ERROR, "El proyecto no tiene ningun documento agregado.", "proyecto")
    else:
        report.add(Severity.OK, f"Total de documentos a insertar: {total_docs}.", "proyecto")

    # -- Salida -----------------------------------------------------------
    if not project.settings.output_dir:
        report.add(
            Severity.WARNING,
            "No se definio carpeta de salida; se pedira al generar el dossier.",
            "salida",
        )

    return report


def _validate_document(report: ValidationReport, doc, section_label: str) -> None:
    path = Path(doc.source_path)
    target = f"{section_label} / {doc.name}"

    if not doc.source_path or not path.exists():
        report.add(Severity.ERROR, f"Archivo no encontrado: '{doc.name}'.", target)
        return

    ok, err = pdf_engine.is_pdf_readable(str(path))
    if not ok:
        if "contrasena" in (err or ""):
            report.add(Severity.ERROR, f"'{doc.name}' esta protegido con contrasena: {err}", target)
        else:
            report.add(Severity.ERROR, f"'{doc.name}' no se pudo leer: {err}", target)
        return

    if doc.has_signature:
        if doc.will_be_flattened:
            report.add(
                Severity.WARNING,
                f"'{doc.name}' contiene firma digital y sera aplanado antes de incorporarse.",
                target,
            )
        else:
            report.add(
                Severity.WARNING,
                f"'{doc.name}' contiene firma digital y se conservara sin aplanar "
                "(la firma visible podria alterarse al combinarse).",
                target,
            )
