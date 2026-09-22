"""Renderizado del patron de nombre configurable para el PDF final."""
from __future__ import annotations

from app.utils.paths import safe_filename


def render_naming_pattern(pattern: str, context: dict[str, str]) -> str:
    """Reemplaza variables ``{codigo}``, ``{pozo}``, etc. en el patron de nombre.

    Las variables ausentes en ``context`` se reemplazan por cadena vacia en
    vez de lanzar un error, para no bloquear la generacion por un campo de
    metadata sin completar.
    """
    safe_context = {k: (v or "") for k, v in context.items()}

    class _DefaultDict(dict):
        def __missing__(self, key):  # noqa: D105
            return ""

    rendered = pattern.format_map(_DefaultDict(safe_context))
    rendered = "-".join(part for part in rendered.split("-") if part.strip())
    return safe_filename(rendered or "dossier")
