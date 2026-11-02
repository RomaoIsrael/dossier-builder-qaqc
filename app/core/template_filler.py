"""Generacion de la plantilla PDF del dossier a partir de un Word (.docx).

Dossier Builder QA/QC usa como "plantilla" del dossier un PDF con caratula,
indice y paginas separadoras de seccion con bookmarks (ver README). Hasta
ahora ese PDF habia que prepararlo a mano fuera del programa. Este modulo
genera ese PDF automaticamente a partir de una plantilla Word versionada
con la aplicacion (ver assets/templates/), completando los campos variables
-- resaltados en amarillo en el Word original, como guia visual para quien
edita la plantilla -- con los datos del proyecto actual.

Flujo: plantilla Word (fija, en assets/templates/) -> copia con los campos
completados (python-docx, sin tocar disco mas que para guardar el
resultado) -> conversion a PDF (ver app.core.word_pdf_converter: Microsoft
Word via automatizacion COM, Windows unicamente). Los encabezados ("Heading
1"/"Heading 2") de la plantilla Word se convierten en marcadores del PDF
automaticamente durante esa conversion (comportamiento estandar de Word),
asi que el PDF resultante se puede usar como ``project.template_path``
exactamente igual que un PDF preparado y subido a mano.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Optional

import docx
from docx.text.paragraph import Paragraph

from app.core.word_pdf_converter import convert_docx_to_pdf_with_word
from app.models.project_model import ProjectMetadata
from app.services.logger import get_logger
from app.utils.paths import generated_templates_dir, resource_path

logger = get_logger("template_filler")

LDSS_TEMPLATE_RESOURCE = "assets/templates/ldss.docx"

_NS_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

_CODE_LIKE_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-]{8,}$")
_YEAR_LIKE_RE = re.compile(r"^\d{4}$")


class TemplateFillError(Exception):
    """No se pudo completar la plantilla Word con los datos del proyecto."""


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def _iter_all_paragraphs(document):
    """Recorre TODOS los parrafos del documento: los del cuerpo normal
    (``document.paragraphs``) y, ademas, los que estan dentro de cuadros de
    texto (``w:txbxContent``), que ``document.paragraphs`` no alcanza a ver.
    La caratula del CD de la plantilla LDSS esta armada enteramente con
    cuadros de texto posicionados sobre el dibujo del CD."""
    yield from document.paragraphs
    fallback_parent = document.paragraphs[0]._parent if document.paragraphs else document.element.body
    body = document.element.body
    for txbx in body.findall(f".//{_NS_W}txbxContent"):
        for p_element in txbx.findall(f"{_NS_W}p"):
            yield Paragraph(p_element, fallback_parent)


def _highlighted_runs(paragraph) -> list:
    return [r for r in paragraph.runs if r.font.highlight_color is not None]


def _is_fully_highlighted(paragraph) -> bool:
    runs_with_text = [r for r in paragraph.runs if r.text]
    if not runs_with_text:
        return False
    return all(r.font.highlight_color is not None for r in runs_with_text)


def _set_run_group_text(runs: list, new_text: str) -> None:
    """Pone ``new_text`` en el primer run de ``runs`` y vacia el resto, para
    reemplazar un valor que Word partio en varios runs -- algo muy comun:
    ej. 'CLBC-058H' guardado como 4 runs separados 'CLBC', '-', '058', 'H'
    por como quedo aplicado el resaltado/formato al escribirlo. Vaciar en
    vez de borrar los runs sobrantes evita tener que tocar la estructura
    XML del parrafo (reordenar runs, fusionar <w:rPr>, etc.)."""
    if not runs:
        return
    runs[0].text = new_text
    for run in runs[1:]:
        run.text = ""


def _fill_reacondicionamiento(paragraph, wo_number: str) -> bool:
    if not paragraph.text.strip().upper().startswith("REACONDICIONAMIENTO #"):
        return False
    highlighted = _highlighted_runs(paragraph)
    if not highlighted:
        return False
    _set_run_group_text(highlighted, wo_number)
    return True


def _fill_labeled_field(paragraph, label_prefix: str, value: str) -> bool:
    """Para parrafos tipo 'PAD: CULEBRA 21', 'POZO: CLBC-058H',
    'LOCACION: CULEBRA': ``label_prefix`` es el texto fijo (sin resaltar) al
    comienzo del parrafo (ej. 'POZO:', sin tilde: la comparacion ignora
    tildes y mayusculas/minusculas); se reemplazan los runs resaltados que
    le siguen. Coincide tanto con la portada como con la caratula del CD
    (ambas tienen un parrafo 'POZO: ...')."""
    normalized = _strip_accents(paragraph.text.strip()).upper()
    if not normalized.startswith(_strip_accents(label_prefix).upper()):
        return False
    highlighted = _highlighted_runs(paragraph)
    if not highlighted:
        return False
    _set_run_group_text(highlighted, value)
    return True


def _fill_mes_anio_cover(paragraph, mes: str, anio: str) -> bool:
    """La fecha de portada ('AGOSTO/2024') no tiene ninguna etiqueta fija y
    todo el parrafo le pertenece a ella sola: se identifica porque contiene
    '/' y tiene al menos un run resaltado. A diferencia de los demas campos,
    aqui el separador '/' (y a veces un espacio final) son SUS PROPIOS runs
    SIN resaltar intercalados entre los resaltados (ej. 'AGOSTO'[amarillo],
    '/'[sin resaltar], '202'[amarillo], '4'[amarillo], ' '[sin resaltar]),
    asi que no alcanza con tocar solo los runs resaltados: hay que
    reemplazar TODOS los runs del parrafo por el valor completo nuevo."""
    if "/" not in paragraph.text:
        return False
    if not _highlighted_runs(paragraph):
        return False
    runs = [r for r in paragraph.runs if r.text]
    if not runs:
        return False
    _set_run_group_text(runs, f"{mes}/{anio}")
    return True


def _fill_bare_codigo_or_anio(paragraph, codigo: str, anio: str) -> bool:
    """En la caratula del CD, el codigo del documento y el ano aparecen
    'desnudos' (sin ninguna etiqueta tipo 'CODIGO:') dentro de su propio
    parrafo, enteramente resaltado. Se distinguen entre si por forma: el
    codigo es una cadena alfanumerica larga con guiones, el ano son 4
    digitos solos."""
    if not _is_fully_highlighted(paragraph):
        return False
    text = paragraph.text.strip().upper()
    highlighted = _highlighted_runs(paragraph)
    if _CODE_LIKE_RE.match(text):
        _set_run_group_text(highlighted, codigo)
        return True
    if _YEAR_LIKE_RE.match(text):
        _set_run_group_text(highlighted, anio)
        return True
    return False


def _fill_cd_pozo_wo_line(paragraph, pozo: str, wo_number: str) -> bool:
    """Linea 'LDSS CLBC-058H WO#01' de la caratula del CD: el pozo y el
    numero de WO estan en el MISMO grupo de runs resaltados, uno despues
    del otro (sin etiqueta propia para cada uno). Se ubica el ultimo run
    resaltado que empieza con 'WO#' como el valor de WO; todo lo resaltado
    ANTES de ese run es el pozo."""
    if not paragraph.text.strip().upper().startswith("LDSS"):
        return False
    highlighted = _highlighted_runs(paragraph)
    if not highlighted:
        return False
    wo_index = next((i for i, r in enumerate(highlighted) if r.text.strip().upper().startswith("WO#")), None)
    if wo_index is None:
        # No se encontro el patron 'WO#...' esperado: se completa solo el
        # pozo (mejor resultado parcial que no completar nada).
        _set_run_group_text(highlighted, pozo)
        return True
    pozo_runs = highlighted[:wo_index]
    wo_runs = highlighted[wo_index:]
    if pozo_runs:
        _set_run_group_text(pozo_runs, f"{pozo} ")
    _set_run_group_text(wo_runs, f"WO#{wo_number}")
    return True


def fill_ldss_template(metadata: ProjectMetadata, output_docx_path: str) -> str:
    """Genera en ``output_docx_path`` una copia de la plantilla LDSS con los
    6 campos variables completados (numero de reacondicionamiento, codigo,
    PAD, pozo, locacion, mes/ano), tanto en la portada como en la caratula
    del CD. El resto del documento (secciones, titulos, logos) queda tal
    cual esta en la plantilla original -- incluidos sus encabezados Word,
    que luego se convierten en los marcadores del PDF final."""
    template_path = resource_path(LDSS_TEMPLATE_RESOURCE)
    if not template_path.exists():
        raise TemplateFillError(f"No se encontro la plantilla LDSS en '{template_path}'.")

    wo_number = (metadata.wo or "").strip() or "00"
    codigo = (metadata.codigo or "").strip()
    pad = (metadata.pad or "").strip()
    pozo = (metadata.pozo or "").strip()
    locacion = (metadata.locacion or "").strip()
    mes = (metadata.mes or "").strip().upper()
    anio = (metadata.anio or "").strip()

    try:
        document = docx.Document(str(template_path))
    except Exception as exc:  # noqa: BLE001 - un .docx danado no debe tumbar nada
        raise TemplateFillError(f"No se pudo abrir la plantilla LDSS: {exc}") from exc

    filled_any = {
        "reacondicionamiento": False,
        "codigo": False,
        "pad": False,
        "pozo": False,
        "locacion": False,
        "mes_anio": False,
        "cd_codigo_o_anio": False,
        "cd_pozo_wo": False,
    }

    for paragraph in _iter_all_paragraphs(document):
        if _fill_reacondicionamiento(paragraph, wo_number):
            filled_any["reacondicionamiento"] = True
            continue
        if _fill_labeled_field(paragraph, "CODIGO:", codigo):
            filled_any["codigo"] = True
            continue
        if _fill_labeled_field(paragraph, "PAD:", pad):
            filled_any["pad"] = True
            continue
        if _fill_labeled_field(paragraph, "POZO:", pozo):
            filled_any["pozo"] = True
            continue
        if _fill_labeled_field(paragraph, "LOCACION:", locacion):
            filled_any["locacion"] = True
            continue
        if _fill_mes_anio_cover(paragraph, mes, anio):
            filled_any["mes_anio"] = True
            continue
        if _fill_cd_pozo_wo_line(paragraph, pozo, wo_number):
            filled_any["cd_pozo_wo"] = True
            continue
        if _fill_bare_codigo_or_anio(paragraph, codigo, anio):
            filled_any["cd_codigo_o_anio"] = True
            continue

    missing = [name for name, done in filled_any.items() if not done]
    if missing:
        logger.warning(
            "La plantilla LDSS no tenia (o no se reconocio) el campo esperado %s. "
            "Se genero la plantilla igual, pero conviene revisarla manualmente.",
            missing,
        )

    output_path = Path(output_docx_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        document.save(str(output_path))
    except Exception as exc:  # noqa: BLE001
        raise TemplateFillError(f"No se pudo guardar la plantilla completada: {exc}") from exc

    return str(output_path)


def generate_ldss_template_pdf(metadata: ProjectMetadata, project_id: str) -> str:
    """Genera la plantilla PDF completa de un proyecto LDSS: completa la
    plantilla Word con los datos del proyecto (``fill_ldss_template``) y la
    convierte a PDF con Microsoft Word (``convert_docx_to_pdf_with_word``,
    Windows unicamente). El resultado queda en una ubicacion estable (no
    temporal, ver ``generated_templates_dir``) identificada por
    ``project_id``, para que ``project.template_path`` siga siendo valido
    mientras el proyecto exista, no solo durante esta sesion.

    Puede lanzar ``TemplateFillError`` o ``WordConversionError`` (ver
    app.core.word_pdf_converter); ambas pensadas para mostrarse tal cual al
    usuario, porque ya explican la causa real en espanol.
    """
    target_dir = generated_templates_dir()
    base_name = f"{project_id}_ldss"
    docx_path = target_dir / f"{base_name}.docx"
    pdf_path = target_dir / f"{base_name}.pdf"

    fill_ldss_template(metadata, str(docx_path))
    convert_docx_to_pdf_with_word(str(docx_path), str(pdf_path))
    return str(pdf_path)
