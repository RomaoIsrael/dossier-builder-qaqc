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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.models.project_model import Project
from app.services.database import DatabaseService
from app.services.logger import get_logger
from app.utils.paths import app_data_dir

logger = get_logger("project")

PROJECT_EXTENSION = ".dossierproj"
_AUTOSAVE_SUFFIX = ".autosave.json"


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

    # -- Autoguardado / recuperacion ante cierre inesperado ------------------
    #
    # Ademas del archivo .dossierproj que el usuario guarda explicitamente
    # (boton "Guardar"), se mantiene una copia de autoguardado por proyecto,
    # actualizada automaticamente mientras se trabaja (ver MainWindow), para
    # no perder avances si la aplicacion se cierra de forma inesperada antes
    # de guardar. Vive aparte, en AppData, identificada por el id del
    # proyecto (no por su ruta), para que funcione incluso con un proyecto
    # que todavia nunca se guardo en disco.

    def autosave_dir(self) -> Path:
        path = app_data_dir() / "autosave"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def autosave_path(self, project: Project) -> Path:
        return self.autosave_dir() / f"{project.id}{_AUTOSAVE_SUFFIX}"

    def build_autosave_wrapper(self, project: Project) -> dict:
        """Parte RAPIDA del autoguardado (solo recorre estructuras en
        memoria, nunca toca disco): se llama desde el hilo principal. El
        diccionario que devuelve es una copia nueva e independiente de
        ``project`` (``project.to_dict()`` no reutiliza listas/diccionarios
        vivos), asi que es seguro pasarlo a ``write_autosave_wrapper`` desde
        un hilo de fondo mientras el usuario sigue editando el proyecto."""
        return {
            "autosaved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "original_path": project.project_file_path,
            "project": project.to_dict(),
        }

    def write_autosave_wrapper(self, wrapper: dict, path: Path) -> None:
        """Parte LENTA del autoguardado (la escritura a disco en si): pensada
        para llamarse desde un hilo de fondo, para que un disco lento
        (antivirus escaneando, OneDrive sincronizando, etc.) no congele la
        interfaz mientras tanto."""
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(wrapper, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(path)

    def autosave(self, project: Project) -> Path:
        """Guarda una copia de respaldo del estado actual del proyecto, sin
        tocar ``project_file_path`` ni el archivo .dossierproj real. Version
        sincrona (bloquea hasta terminar); la ventana principal usa en su
        lugar ``build_autosave_wrapper`` + ``write_autosave_wrapper`` desde
        un hilo de fondo (``AutosaveWorker``), para no congelar la interfaz."""
        path = self.autosave_path(project)
        wrapper = self.build_autosave_wrapper(project)
        self.write_autosave_wrapper(wrapper, path)
        return path

    def discard_autosave(self, project: Project) -> None:
        """Borra el autoguardado de ``project`` (ya no hace falta: el archivo
        .dossierproj real quedo al dia, o el usuario descarto los cambios)."""
        try:
            self.autosave_path(project).unlink(missing_ok=True)
        except OSError:
            logger.warning("No se pudo borrar el autoguardado de '%s'", project.name)

    def list_recoverable_autosaves(self) -> list[dict]:
        """Autoguardados cuyo archivo .dossierproj original esta ausente o
        desactualizado respecto al autoguardado (indicio de un cierre
        inesperado con cambios sin guardar). Los autoguardados que ya estan
        al dia con su archivo real se borran en silencio aqui mismo, para no
        volver a preguntar por ellos. No carga el :class:`Project` completo
        todavia, solo los metadatos livianos necesarios para decidir."""
        recoverable: list[dict] = []
        for path in self.autosave_dir().glob(f"*{_AUTOSAVE_SUFFIX}"):
            try:
                wrapper = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Autoguardado ilegible '%s': %s", path, exc)
                continue

            original_path = wrapper.get("original_path")
            if original_path and Path(original_path).exists():
                try:
                    is_up_to_date = Path(original_path).stat().st_mtime >= path.stat().st_mtime
                except OSError:
                    is_up_to_date = False
                if is_up_to_date:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    continue

            recoverable.append(
                {
                    "autosave_path": str(path),
                    "autosaved_at": wrapper.get("autosaved_at", ""),
                    "original_path": original_path,
                    "project_name": wrapper.get("project", {}).get("name", "Proyecto sin nombre"),
                }
            )
        return recoverable

    def load_autosave(self, autosave_path: str) -> Project:
        wrapper = json.loads(Path(autosave_path).read_text(encoding="utf-8"))
        project = Project.from_dict(wrapper["project"])
        project.project_file_path = wrapper.get("original_path")
        return project

    def discard_autosave_at(self, autosave_path: str) -> None:
        try:
            Path(autosave_path).unlink(missing_ok=True)
        except OSError:
            logger.warning("No se pudo borrar el autoguardado '%s'", autosave_path)
