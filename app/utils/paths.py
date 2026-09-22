"""Rutas estandar de la aplicacion (config, datos, logs, temporales)."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

APP_NAME = "DossierBuilderQAQC"


def app_data_dir() -> Path:
    """Directorio donde se guardan configuracion, base de datos y logs.

    En Windows usa %APPDATA%\\DossierBuilderQAQC. En otros sistemas (para
    desarrollo/pruebas) usa ~/.dossierbuilderqaqc.
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        path = Path(base) / APP_NAME
    else:
        path = Path.home() / f".{APP_NAME.lower()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def temp_root_dir() -> Path:
    """Directorio raiz para archivos temporales de procesamiento (aplanado, ensamblado)."""
    path = Path(tempfile.gettempdir()) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: str) -> str:
    """Elimina caracteres invalidos para nombres de archivo en Windows."""
    invalid = '<>:"/\\|?*'
    cleaned = "".join(c for c in name if c not in invalid).strip()
    return cleaned or "sin_nombre"
