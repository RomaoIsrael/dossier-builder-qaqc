"""Calculo de checksums SHA-256 para trazabilidad documental."""
from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK_SIZE = 1024 * 1024  # 1 MB, para no cargar PDFs grandes completos en memoria.


def sha256_file(path: str | Path) -> str:
    """Calcula el SHA-256 de un archivo leyendolo por bloques."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()
