"""Manejo de espacios de trabajo temporales para una generacion de dossier."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from app.utils.paths import temp_root_dir


class GenerationWorkspace:
    """Carpeta temporal aislada para una ejecucion de generacion de dossier.

    Se usa como context manager: al salir limpia los archivos temporales,
    salvo que ``keep`` se marque en True (por ejemplo para depuracion).
    """

    def __init__(self, keep: bool = False):
        self.keep = keep
        self.root: Path = temp_root_dir() / f"gen_{uuid.uuid4().hex[:12]}"

    def __enter__(self) -> "GenerationWorkspace":
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "flattened").mkdir(exist_ok=True)
        (self.root / "assembly").mkdir(exist_ok=True)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if not self.keep and self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)

    @property
    def flattened_dir(self) -> Path:
        return self.root / "flattened"

    @property
    def assembly_dir(self) -> Path:
        return self.root / "assembly"
