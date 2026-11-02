import sys

import docx
import pytest

from app.core import template_filler
from app.core.word_pdf_converter import WordConversionError, convert_docx_to_pdf_with_word
from app.models.project_model import ProjectMetadata

_NS_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _sample_metadata() -> ProjectMetadata:
    return ProjectMetadata(
        pozo="ABCD-123H",
        wo="07",
        codigo="99X9999-ABCD-01-LSS-999-1",
        pad="NUEVO PAD 5",
        locacion="NUEVA LOCACION",
        mes="SEPTIEMBRE",
        anio="2025",
    )


def _all_paragraph_texts(document) -> list[str]:
    """Junta el texto de parrafos del cuerpo y de todos los cuadros de
    texto (la caratula del CD de la plantilla LDSS esta hecha con cuadros
    de texto, que document.paragraphs no alcanza a ver)."""
    texts = [p.text for p in document.paragraphs if p.text.strip()]
    body = document.element.body
    for txbx in body.findall(f".//{_NS_W}txbxContent"):
        for p in txbx.findall(f".//{_NS_W}p"):
            run_text = "".join(
                (r.find(f"{_NS_W}t").text or "")
                for r in p.findall(f"{_NS_W}r")
                if r.find(f"{_NS_W}t") is not None
            )
            if run_text.strip():
                texts.append(run_text)
    return texts


def test_fill_ldss_template_substitutes_all_six_fields(tmp_path):
    metadata = _sample_metadata()
    output_path = tmp_path / "ldss_filled.docx"

    template_filler.fill_ldss_template(metadata, str(output_path))

    assert output_path.exists()
    document = docx.Document(str(output_path))
    texts = _all_paragraph_texts(document)

    # Portada
    assert "REACONDICIONAMIENTO #07" in texts
    assert "CODIGO: 99X9999-ABCD-01-LSS-999-1" in texts
    assert "PAD: NUEVO PAD 5" in texts
    assert "POZO: ABCD-123H" in texts
    assert "LOCACIÓN: NUEVA LOCACION" in texts
    assert "SEPTIEMBRE/2025" in texts

    # Caratula del CD (cuadros de texto)
    assert "LDSS ABCD-123H WO#07" in texts
    assert "99X9999-ABCD-01-LSS-999-1" in texts
    assert "2025" in texts


def test_fill_ldss_template_removes_all_highlighting(tmp_path):
    """El resaltado amarillo de la plantilla original es solo una guia
    visual para saber que datos cambiar por pozo: no debe quedar en el
    documento final que termina convertido a PDF."""
    output_path = tmp_path / "ldss_filled.docx"
    template_filler.fill_ldss_template(_sample_metadata(), str(output_path))

    document = docx.Document(str(output_path))
    highlighted = [
        run.text
        for paragraph in template_filler._iter_all_paragraphs(document)
        for run in paragraph.runs
        if run.font.highlight_color is not None
    ]
    assert highlighted == []


def test_fill_ldss_template_preserves_fixed_fields_not_in_the_six(tmp_path):
    """Contrato y bloque NO estan en la lista de 6 campos pedidos: deben
    quedar exactamente igual que en la plantilla original."""
    metadata = _sample_metadata()
    output_path = tmp_path / "ldss_filled.docx"

    template_filler.fill_ldss_template(metadata, str(output_path))

    document = docx.Document(str(output_path))
    texts = _all_paragraph_texts(document)
    assert "CONTRATO N.º: O-02158-PAM-EP-2015" in texts
    assert "BLOQUE: 61" in texts
    assert "O-02158-PAM-EP-2015" in texts  # linea suelta en la caratula del CD


def test_fill_ldss_template_keeps_section_headings_intact(tmp_path):
    """Los encabezados (Heading 1/2) son los que se convierten en
    marcadores del PDF al exportar: no deben tocarse al completar los
    campos variables."""
    metadata = _sample_metadata()
    output_path = tmp_path / "ldss_filled.docx"

    template_filler.fill_ldss_template(metadata, str(output_path))

    document = docx.Document(str(output_path))
    headings = [p.text for p in document.paragraphs if p.style.name.startswith("Heading")]
    assert "1. CONCILIACIÓN DE MATERIALES" in headings
    assert "CERTIFICADOS DE CALIDAD" in headings
    assert "ANEXOS" in headings


def test_fill_ldss_template_raises_clear_error_if_template_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(template_filler, "resource_path", lambda relative: tmp_path / "no_existe.docx")

    with pytest.raises(template_filler.TemplateFillError):
        template_filler.fill_ldss_template(_sample_metadata(), str(tmp_path / "out.docx"))


def test_convert_docx_to_pdf_with_word_raises_clearly_outside_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(WordConversionError):
        convert_docx_to_pdf_with_word(str(tmp_path / "in.docx"), str(tmp_path / "out.pdf"))
