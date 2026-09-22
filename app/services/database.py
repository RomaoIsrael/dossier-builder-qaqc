"""Indice SQLite de proyectos y de generaciones de dossiers.

Decision de diseno: cada proyecto se guarda como archivo JSON portable
(*.dossierproj, ver app.core.project_io) junto a los documentos del usuario,
para que pueda copiarse, versionarse con git o revisarse a mano sin abrir la
aplicacion. SQLite se usa como *indice* local: lista de proyectos recientes,
metadatos de busqueda rapida y el historial de generaciones (para
trazabilidad: que dossier se genero, cuando, con que hash). Esto evita
guardar los PDF binarios dentro de la base de datos (tal como pide el
requerimiento) y a la vez ofrece consultas rapidas sin tener que abrir y
parsear cada .dossierproj del disco.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from app.utils.paths import app_data_dir

_DB_FILENAME = "dossierbuilder.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    file_path TEXT NOT NULL UNIQUE,
    template_path TEXT,
    created_at TEXT NOT NULL,
    modified_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    output_path TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    total_pages INTEGER,
    total_documents INTEGER,
    flattened_count INTEGER,
    sha256_final TEXT,
    had_errors INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (project_id) REFERENCES projects (id)
);
"""


class DatabaseService:
    """Envoltorio simple sobre sqlite3 para el indice local de la aplicacion."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path: Path = db_path or (app_data_dir() / _DB_FILENAME)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def upsert_project(
        self, project_id: str, name: str, file_path: str, template_path: str, created_at: str, modified_at: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO projects (id, name, file_path, template_path, created_at, modified_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    file_path=excluded.file_path,
                    template_path=excluded.template_path,
                    modified_at=excluded.modified_at
                """,
                (project_id, name, file_path, template_path, created_at, modified_at),
            )

    def list_projects(self, limit: int = 50) -> list[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM projects ORDER BY modified_at DESC LIMIT ?", (limit,)
            )
            return cur.fetchall()

    def remove_project(self, project_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    def record_generation(
        self,
        project_id: str,
        output_path: str,
        generated_at: str,
        total_pages: int,
        total_documents: int,
        flattened_count: int,
        sha256_final: str,
        had_errors: bool,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO generations
                    (project_id, output_path, generated_at, total_pages, total_documents,
                     flattened_count, sha256_final, had_errors)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    output_path,
                    generated_at,
                    total_pages,
                    total_documents,
                    flattened_count,
                    sha256_final,
                    1 if had_errors else 0,
                ),
            )
            return int(cur.lastrowid)

    def list_generations(self, project_id: str, limit: int = 20) -> list[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM generations WHERE project_id = ? ORDER BY generated_at DESC LIMIT ?",
                (project_id, limit),
            )
            return cur.fetchall()
