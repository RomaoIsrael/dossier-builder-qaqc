"""Lanzador en la raiz del repositorio: ``python main.py``.

Este archivo solo existe para que el comando pedido en los requisitos
(``python main.py``) funcione ejecutandolo desde la raiz del proyecto. La
implementacion real vive en ``app/main.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
