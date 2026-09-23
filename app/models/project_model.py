"""Modelo de datos raiz: un proyecto de dossier completo."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from app.models.section_model import SectionNode


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ProjectMetadata:
    """Campos de encabezado / metadatos que se aplican al PDF final."""

    proyecto: str = ""
    pozo: str = ""
    wo: str = ""
    codigo: str = ""
    contrato: str = ""
    bloque: str = ""
    fecha: str = ""
    revision: str = "0"
    tipo: str = ""

    titulo_pdf: str = ""
    autor_pdf: str = ""
    asunto_pdf: str = ""
    keywords_pdf: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectMetadata":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def as_naming_context(self) -> dict[str, str]:
        return {
            "proyecto": self.proyecto,
            "pozo": self.pozo,
            "wo": self.wo,
            "codigo": self.codigo,
            "contrato": self.contrato,
            "bloque": self.bloque,
            "fecha": self.fecha,
            "revision": self.revision,
            "tipo": self.tipo,
        }


@dataclass
class ProjectSettings:
    """Configuracion de procesamiento asociada al proyecto."""

    flatten_dpi: int = 450
    flatten_image_format: str = "jpeg"  # "jpeg" | "png"
    flatten_jpeg_quality: int = 95
    signature_mode: str = "auto"  # "auto" | "ask" | "never"
    output_naming_pattern: str = "{codigo}-{pozo}-{tipo}-{revision}"
    output_dir: str = ""
    create_bookmarks_for_individual_docs: bool = False
    keep_backup_of_signed_originals: bool = True
    generate_automatic_index: bool = False
    include_documents_in_index: bool = False

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectSettings":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Project:
    """Un proyecto de dossier: plantilla + arbol de secciones + configuracion."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Nuevo proyecto"
    template_path: str = ""
    template_page_count: Optional[int] = None

    metadata: ProjectMetadata = field(default_factory=ProjectMetadata)
    settings: ProjectSettings = field(default_factory=ProjectSettings)
    sections: list[SectionNode] = field(default_factory=list)

    created_at: str = field(default_factory=_now_iso)
    modified_at: str = field(default_factory=_now_iso)

    # Ruta del archivo .dossierproj (JSON) donde se guardo por ultima vez.
    project_file_path: Optional[str] = None

    schema_version: int = 1

    # Control de versiones/generaciones: cuantas veces se genero el dossier
    # final de este proyecto, y el nombre/fecha de la ultima vez, para poder
    # ofrecer "mantener el mismo nombre" en generaciones siguientes y dejar
    # trazabilidad de revisiones en el manifest/reporte.
    generation_count: int = 0
    last_output_filename: str = ""
    last_generated_at: str = ""

    def touch(self) -> None:
        self.modified_at = _now_iso()

    def iter_all_sections(self):
        for root in self.sections:
            yield from root.iter_all_sections()

    def find_section(self, section_id: str) -> Optional[SectionNode]:
        for node in self.iter_all_sections():
            if node.id == section_id:
                return node
        return None

    def total_documents(self) -> int:
        return sum(len(n.documents) for n in self.iter_all_sections())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "template_path": self.template_path,
            "template_page_count": self.template_page_count,
            "metadata": self.metadata.to_dict(),
            "settings": self.settings.to_dict(),
            "sections": [s.to_dict() for s in self.sections],
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "generation_count": self.generation_count,
            "last_output_filename": self.last_output_filename,
            "last_generated_at": self.last_generated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", "Proyecto"),
            template_path=data.get("template_path", ""),
            template_page_count=data.get("template_page_count"),
            metadata=ProjectMetadata.from_dict(data.get("metadata", {})),
            settings=ProjectSettings.from_dict(data.get("settings", {})),
            sections=[SectionNode.from_dict(s) for s in data.get("sections", [])],
            created_at=data.get("created_at", _now_iso()),
            modified_at=data.get("modified_at", _now_iso()),
            schema_version=data.get("schema_version", 1),
            generation_count=data.get("generation_count", 0),
            last_output_filename=data.get("last_output_filename", ""),
            last_generated_at=data.get("last_generated_at", ""),
        )
