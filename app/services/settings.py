"""Configuracion global de la aplicacion, persistida como JSON en AppData."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.utils.paths import app_data_dir

_SETTINGS_FILENAME = "settings.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_recent_projects(raw: Any) -> list[dict]:
    """Convierte entradas viejas (listas de rutas en texto plano, de antes
    de que existiera la fecha/hora) al formato actual ``{"path", "opened_at"}``,
    para que un settings.json guardado por una version anterior no se rompa."""
    normalized: list[dict] = []
    for entry in raw or []:
        if isinstance(entry, str):
            normalized.append({"path": entry, "opened_at": None})
        elif isinstance(entry, dict) and entry.get("path"):
            normalized.append({"path": entry["path"], "opened_at": entry.get("opened_at")})
    return normalized


@dataclass
class AppSettings:
    # General
    language: str = "es"
    theme: str = "light"  # "light" | "dark"

    # PDF / rasterizacion
    default_flatten_dpi: int = 450
    default_flatten_image_format: str = "jpeg"
    default_flatten_jpeg_quality: int = 95
    optimize_output: bool = True

    # Firmas
    signature_mode: str = "auto"  # "auto" | "ask" | "never"

    # Salida
    default_output_dir: str = ""
    default_naming_pattern: str = "{codigo}-{pozo}-{tipo}-{revision}"
    create_backup_structure: bool = True

    # Bookmarks
    create_bookmarks_for_individual_docs: bool = False

    # Rendimiento
    max_preview_dpi: int = 100
    # Cada entrada: {"path": str, "opened_at": str ISO (UTC) | None}.
    # "opened_at" se actualiza tanto al abrir como al guardar un proyecto,
    # asi el menu "Proyectos recientes" muestra cuando se trabajo con cada
    # uno por ultima vez, no solo el orden.
    recent_projects: list[dict] = field(default_factory=list)

    # Panel de miniaturas: tamano de exhibicion preferido por el usuario
    # (ancho en pixeles), para que se recuerde entre sesiones.
    thumbnail_rail_zoom: int = 130

    # PDF de una sola pagina que se inserta al marcar una seccion/subseccion
    # como "NO APLICA" (ver boton en la ventana principal). Se recuerda para
    # no tener que elegirlo cada vez.
    default_no_aplica_template_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        known = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known}
        filtered["recent_projects"] = _normalize_recent_projects(filtered.get("recent_projects"))
        return cls(**filtered)


class SettingsService:
    """Carga/guarda AppSettings en <app_data_dir>/settings.json."""

    def __init__(self):
        self._path: Path = app_data_dir() / _SETTINGS_FILENAME
        self.settings: AppSettings = self._load()

    def _load(self) -> AppSettings:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                return AppSettings.from_dict(data)
            except (json.JSONDecodeError, OSError):
                pass
        return AppSettings()

    def save(self) -> None:
        self._path.write_text(
            json.dumps(self.settings.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def add_recent_project(self, project_path: str, max_items: int = 10) -> None:
        recents = [e for e in self.settings.recent_projects if e.get("path") != project_path]
        recents.insert(0, {"path": project_path, "opened_at": _now_iso()})
        self.settings.recent_projects = recents[:max_items]
        self.save()
