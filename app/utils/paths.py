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


def generated_templates_dir() -> Path:
    """Directorio donde quedan las plantillas PDF generadas automaticamente
    a partir de un Word (ver app.core.template_filler), una por proyecto.
    Se guardan aqui (no en una carpeta temporal del sistema) porque
    ``Project.template_path`` debe seguir siendo legible mientras el
    proyecto exista, no solo durante la sesion en que se genero."""
    path = app_data_dir() / "generated_templates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resource_path(relative: str) -> Path:
    """Resuelve la ruta a un recurso empaquetado con la aplicacion (ej.
    ``assets/icon.ico`` o ``assets/templates/ldss.docx``), tanto corriendo
    desde el codigo fuente como ya compilado en un .exe con PyInstaller (que
    extrae los datos agregados con ``--add-data`` a una carpeta temporal
    indicada en ``sys._MEIPASS``)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    return base / relative


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: str) -> str:
    """Elimina caracteres invalidos para nombres de archivo en Windows."""
    invalid = '<>:"/\\|?*'
    cleaned = "".join(c for c in name if c not in invalid).strip()
    return cleaned or "sin_nombre"
