"""Sugerencia (opcional) de seccion destino segun el nombre del archivo.

La decision final siempre la toma el usuario (ver ``AutoDistributeDialog``):
esto solo calcula una sugerencia por superposicion de palabras clave entre
el nombre del archivo y el titulo de cada seccion, con un pequeno
diccionario de sinonimos para jerga tipica de QA/QC (MTR, GR, etc.) que no
aparece literalmente en los titulos de seccion pero se refiere al mismo
concepto.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Optional

from app.models.section_model import SectionNode

# Sinonimos: token detectado en el archivo -> token equivalente a buscar en
# el titulo de la seccion. Se puede ampliar segun el vocabulario del cliente.
_SYNONYMS: dict[str, str] = {
    "MTR": "CERTIFICADO",
    "CERT": "CERTIFICADO",
    "CERTIF": "CERTIFICADO",
    "GR": "GUIA",
    "REMISION": "GUIA",
    "DIAGRAMAS": "DIAGRAMA",
    "RUN": "PULL",
}

_STOPWORDS = {"DE", "DEL", "LA", "EL", "LOS", "LAS", "Y", "EN", "A", "PARA", "CON", "SIN"}

_TOKEN_RE = re.compile(r"[^A-Z0-9]+")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).upper()


def _tokenize(text: str) -> set[str]:
    normalized = _normalize(text)
    raw_tokens = [t for t in _TOKEN_RE.split(normalized) if t]
    tokens: set[str] = set()
    for token in raw_tokens:
        if token in _STOPWORDS or len(token) < 2:
            continue
        tokens.add(token)
        if token in _SYNONYMS:
            tokens.add(_SYNONYMS[token])
    return tokens


def _score(file_tokens: set[str], title_tokens: set[str]) -> int:
    score = 0
    for f_tok in file_tokens:
        for t_tok in title_tokens:
            if f_tok == t_tok or f_tok in t_tok or t_tok in f_tok:
                score += 1
                break
    return score


def suggest_section(filename: str, sections: list[SectionNode]) -> Optional[SectionNode]:
    """Devuelve la seccion cuyo titulo mejor coincide con el nombre del
    archivo, o ``None`` si no hay ninguna coincidencia razonable.
    """
    file_tokens = _tokenize(Path(filename).stem)
    if not file_tokens:
        return None

    best_section: Optional[SectionNode] = None
    best_score = 0
    for root in sections:
        for node in root.iter_all_sections():
            title_tokens = _tokenize(f"{node.numbering} {node.title}")
            score = _score(file_tokens, title_tokens)
            if score <= 0:
                continue
            # En caso de empate, se prefiere la seccion mas especifica
            # (nivel mas profundo) en vez de la seccion "padre" mas generica.
            is_better = score > best_score or (
                score == best_score and best_section is not None and node.level > best_section.level
            )
            if is_better:
                best_score = score
                best_section = node
    return best_section


def suggest_sections_for_files(filenames: list[str], sections: list[SectionNode]) -> dict[str, Optional[SectionNode]]:
    """Aplica :func:`suggest_section` a varios archivos de una vez."""
    return {filename: suggest_section(filename, sections) for filename in filenames}
