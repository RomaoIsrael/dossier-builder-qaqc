"""Aplanado (rasterizado) de PDF firmados a copias visualmente identicas.

Proceso, tal como lo describe el requerimiento:

    PDF firmado original
    -> renderizacion de cada pagina a alta resolucion
    -> reconstruccion de un PDF visualmente identico
    -> firma visible convertida en contenido plano
    -> incorporacion de esa copia al dossier

Esto NO preserva la validez criptografica de la firma original (eso es
imposible una vez rasterizada la pagina): solo preserva su *apariencia*. El
PDF original firmado nunca se modifica ni se sobrescribe; este modulo
siempre escribe en una ruta de salida nueva.
"""
from __future__ import annotations

from dataclasses import dataclass

import fitz  # PyMuPDF

from app.services.logger import get_logger

logger = get_logger("flattener")

_VALID_DPI = (150, 200, 300, 400)


@dataclass
class FlattenOptions:
    dpi: int = 300
    image_format: str = "jpeg"  # "jpeg" | "png"
    jpeg_quality: int = 90


class FlattenError(Exception):
    """Fallo al rasterizar/aplanar un PDF."""


def flatten_pdf(input_path: str, output_path: str, options: FlattenOptions | None = None) -> str:
    """Genera en ``output_path`` una copia rasterizada de ``input_path``.

    Cada pagina se renderiza a una imagen de alta resolucion y se reinserta
    en una pagina nueva del mismo tamano fisico y orientacion que la
    original, de modo que el resultado se vea igual pero ya no contenga
    texto/objetos vectoriales (ni, por lo tanto, el objeto de firma digital
    original).
    """
    options = options or FlattenOptions()
    if options.dpi not in _VALID_DPI:
        logger.warning("DPI %s fuera de los valores recomendados %s", options.dpi, _VALID_DPI)

    zoom = options.dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    try:
        src = fitz.open(input_path)
    except Exception as exc:  # noqa: BLE001
        raise FlattenError(f"No se pudo abrir '{input_path}' para aplanar: {exc}") from exc

    out = fitz.open()
    try:
        for page_index in range(src.page_count):
            page = src[page_index]

            # page.rect es el mediabox SIN aplicar /Rotate. Si la pagina esta
            # rotada 90/270, el pixmap renderizado queda "acostado" respecto
            # al mediabox, asi que hay que intercambiar ancho/alto de la
            # pagina de salida para que coincida con lo que se ve.
            rotation = page.rotation % 360
            page_width, page_height = page.rect.width, page.rect.height
            if rotation in (90, 270):
                page_width, page_height = page_height, page_width

            pix = page.get_pixmap(matrix=matrix, alpha=False)

            new_page = out.new_page(width=page_width, height=page_height)

            img_format = "jpeg" if options.image_format.lower() == "jpeg" else "png"
            if img_format == "jpeg":
                # PyMuPDF espera "jpg" (no "jpeg") como nombre de formato en Pixmap.tobytes().
                img_bytes = pix.tobytes("jpg", jpg_quality=options.jpeg_quality)
            else:
                img_bytes = pix.tobytes("png")

            new_page.insert_image(new_page.rect, stream=img_bytes)

        out.save(output_path, garbage=4, deflate=True)
        logger.info(
            "Aplanado completo: '%s' -> '%s' (%d paginas, %d DPI)",
            input_path,
            output_path,
            src.page_count,
            options.dpi,
        )
    except Exception as exc:  # noqa: BLE001
        raise FlattenError(f"Fallo al aplanar '{input_path}': {exc}") from exc
    finally:
        src.close()
        out.close()

    return output_path
