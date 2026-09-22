"""Deteccion de firmas digitales/electronicas en un PDF.

IMPORTANTE (ver README, seccion "Firmas digitales"): esto detecta la
*presencia* de campos/objetos de firma para decidir si un documento es
candidato a aplanado antes de incorporarlo al dossier. No implementa (ni
pretende reemplazar) la validacion criptografica de la firma (cadena de
certificados, vigencia, integridad via ByteRange). Esa validacion debe
hacerse, si se necesita, sobre el PDF original guardado en el backup
(00_ORIGINALES_FIRMADOS), nunca sobre la version aplanada.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import fitz  # PyMuPDF

from app.services.logger import get_logger

logger = get_logger("signature_detector")


@dataclass
class SignatureInfo:
    has_signature: bool
    signature_count: int = 0
    details: list[str] = field(default_factory=list)


def detect_signatures(path: str) -> SignatureInfo:
    """Analiza un PDF en busca de indicios de firma digital/electronica.

    Estrategias combinadas:
    1. Widgets de formulario de tipo firma (``/FT /Sig``) en cada pagina,
       expuestos por PyMuPDF como ``PDF_WIDGET_TYPE_SIGNATURE``.
    2. Entradas ``/AcroForm`` con campos de firma a nivel de catalogo,
       incluso si no tienen widget visible en una pagina.
    3. Presencia de ``/ByteRange`` en el PDF crudo, indicador tipico de
       firmas PDF (PKCS#7) y PAdES.
    """
    details: list[str] = []
    signature_count = 0

    try:
        doc = fitz.open(path)
    except Exception as exc:  # noqa: BLE001 - queremos degradar con gracia
        logger.warning("No se pudo analizar firmas en '%s': %s", path, exc)
        return SignatureInfo(has_signature=False, details=[f"No se pudo analizar: {exc}"])

    try:
        for page_index in range(doc.page_count):
            page = doc[page_index]
            try:
                widgets = page.widgets() or []
            except Exception:  # noqa: BLE001
                widgets = []
            for widget in widgets:
                if widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                    signature_count += 1
                    details.append(f"Campo de firma en pagina {page_index + 1} ('{widget.field_name}')")

        try:
            xref_count = doc.xref_length()
            for xref in range(1, xref_count):
                try:
                    obj = doc.xref_object(xref, compressed=True)
                except Exception:  # noqa: BLE001
                    continue
                if "/ByteRange" in obj and "/Contents" in obj:
                    signature_count += 1
                    details.append(f"Objeto de firma (ByteRange) en xref {xref}")
                elif "/FT/Sig" in obj.replace(" ", "") or "/FT /Sig" in obj:
                    signature_count += 1
                    details.append(f"Campo AcroForm /FT /Sig en xref {xref}")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Fallo el escaneo de bajo nivel de firmas en '%s': %s", path, exc)

    finally:
        doc.close()

    # Evitar contar dos veces el mismo campo detectado por widget + xref.
    has_signature = signature_count > 0
    if has_signature:
        logger.info("Firma(s) detectada(s) en '%s': %d indicio(s)", path, signature_count)

    return SignatureInfo(has_signature=has_signature, signature_count=signature_count, details=details)
