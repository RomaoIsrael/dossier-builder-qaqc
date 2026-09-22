"""Gestion de proyectos: crear, guardar, abrir, guardar como, duplicar.

Un proyecto se persiste como archivo JSON (*.dossierproj). Solo se guardan
referencias (rutas) a los PDF de entrada, nunca su contenido binario. El
DatabaseService mantiene un indice SQLite de proyectos recientes para la
pantalla de inicio.
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Optional

from app.models.project_model import Project
from app.services.database import DatabaseService
from app.services.logger import get_logger

logger = get_logger("project")

PROJECT_EXTENSION = ".dossierproj"


class ProjectError(Exception):
    """Error al crear, abrir o guardar un proyecto."""


class ProjectService:
    def __init__(self, database: Optional[DatabaseService] = None):
        self.database = database or DatabaseService()

    # -- Creacion -----------------------------------------------------
    def new_project(self, name: str = "Nuevo proyecto") -> Project:
        project = Project(name=name)
        logger.info("Proyecto nuevo creado en memoria: %s (%s)", name, project.id)
        return project

    # -- Guardado -------------------------------------------------------
    def save(self, project: Project, path: Optional[str] = None) -> Path:
        target = Path(path or project.project_file_path or "")
        if not target.name:
            raise ProjectError("No se especifico una ruta para guardar el proyecto.")
        if target.suffix.lower() != PROJECT_EXTENSION:
            target = target.with_suffix(PROJECT_EXTENSION)

        project.touch()
        target.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = target.with_suffix(target.suffix + ".tmp")
        tmp_path.write_text(json.dumps(project.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(target)

        project.project_file_path = str(target)
        self.database.upsert_project(
            project_id=project.id,
            name=project.name,
            file_path=str(target),
            template_path=project.template_path,
            created_at=project.created_at,
            modified_at=project.modified_at,
        )
        logger.info("Proyecto guardado en %s", target)
        return target

    def save_as(self, project: Project, new_path: str) -> Path:
        project.project_file_path = None
        return self.save(project, new_path)

    # -- Apertura ---------------------------------------------------------
    def open(self, path: str) -> Project:
        p = Path(path)
        if not p.exists():
            raise ProjectError(f"El archivo de proyecto no existe: {path}")
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ProjectError(f"El archivo de proyecto esta corrupto o no es JSON valido: {exc}") from exc

        project = Project.from_dict(data)
        project.project_file_path = str(p)
        logger.info("Proyecto abierto: %s (%s)", project.name, p)
        return project

    # -- Duplicar -----------------------------------------------------------
    def duplicate(self, project: Project, new_path: str, new_name: Optional[str] = None) -> Project:
        clone = Project.from_dict(project.to_dict())
        clone.id = str(uuid.uuid4())
        clone.name = new_name or f"{project.name} (copia)"
        clone.project_file_path = None
        self.save(clone, new_path)
        return clone

    def close(self, project: Project) -> None:
        """No-op explicito: liberar referencias/estado de UI queda a cargo del caller."""
        logger.info("Proyecto cerrado: %s", project.name)
