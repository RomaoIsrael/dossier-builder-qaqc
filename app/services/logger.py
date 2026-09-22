"""Configuracion de logging centralizada (archivo dossierbuilder.log + consola)."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.utils.paths import logs_dir

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_configured = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configura el logger raiz de la aplicacion. Idempotente."""
    global _configured
    root = logging.getLogger("dossierbuilder")
    if _configured:
        return root

    root.setLevel(level)

    log_path = logs_dir() / "dossierbuilder.log"
    file_handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    file_handler.setLevel(level)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    console_handler.setLevel(level)

    root.addHandler(file_handler)
    root.addHandler(console_handler)
    root.propagate = False

    _configured = True
    root.info("Logging inicializado. Archivo: %s", log_path)
    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"dossierbuilder.{name}")
