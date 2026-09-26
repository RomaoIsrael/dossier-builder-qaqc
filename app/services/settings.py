"""Configuracion global de la aplicacion, persistida como JSON en AppData."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.utils.paths import app_data_dir

_SETTINGS_FILENAME = "settings.json"


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
    recent_projects: list[str] = field(default_factory=list)

    # Panel de miniaturas: tamano de exhibicion preferido por el usuario
    # (ancho en pixeles), para que se recuerde entre sesiones.
    thumbnail_rail_zoom: int = 130

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


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
        recents = [p for p in self.settings.recent_projects if p != project_path]
        recents.insert(0, project_path)
        self.settings.recent_projects = recents[:max_items]
        self.save()
