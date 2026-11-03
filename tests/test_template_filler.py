import sys

import docx
import pytest

from app.core import template_filler
from app.core.word_pdf_converter import WordConversionError, convert_docx_to_pdf_with_word
from app.models.project_model import ProjectMetadata

_NS_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _sample_ldss_metadata() -> ProjectMetadata:
    return ProjectMetadata(
        pozo="ABCD-123H",
        wo="07",
        codigo="99X9999-ABCD-01-LSS-999-1",
        pad="NUEVO PAD 5",
        locacion="NUEVA LOCACION",
        mes="SEPTIEMBRE",
        anio="2025",
        contrato="O-NUEVO-CONTRATO-2026",
    )


def _sample_wo_capex_metadata() -> ProjectMetadata:
    return ProjectMetadata(
        pozo="ZZZZ-999X",
        wo="19",
        codigo="88Y7777-ZZZZ-09-RDP-888-2",
        pad="PAD DISTINTO 9",
        locacion="OTRA LOCACION",
        mes="MARZO",
        anio="2027",
        contrato="O-OTRO-CONTRATO-XYZ",
    )


def _sample_pci_metadata() -> ProjectMetadata:
    return ProjectMetadata(
        pozo="QWER-555Z",
        wo="",  # PCI no usa numero de reacondicionamiento/WO
        codigo="77H1111-QWER-05-PCI-444-3",
        pad="PAD PRUEBA 7",
        locacion="LOCACION PRUEBA",
        mes="JUNIO",
        anio="2028",
        contrato="O-TEST-CONTRATO-999",
    )


def _all_paragraph_texts(document) -> list[str]:
    """Junta el texto de parrafos del cuerpo y de todos los cuadros de
    texto (la caratula del CD de estas plantillas esta hecha con cuadros
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


def _assert_no_highlighting_remains(document) -> None:
    highlighted = [
        run.text
        for paragraph in template_filler._iter_all_paragraphs(document)
        for run in paragraph.runs
        if run.font.highlight_color is not None
    ]
    assert highlighted == []


# -- LDSS -------------------------------------------------------------------


def test_fill_ldss_template_substitutes_all_fields(tmp_path):
    metadata = _sample_ldss_metadata()
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
    assert "CONTRATO N.º: O-NUEVO-CONTRATO-2026" in texts

    # Caratula del CD (cuadros de texto)
    assert "LDSS ABCD-123H WO#07" in texts
    assert "99X9999-ABCD-01-LSS-999-1" in texts
    assert "2025" in texts
    assert "O-NUEVO-CONTRATO-2026" in texts  # linea suelta del contrato


def test_fill_ldss_template_removes_all_highlighting(tmp_path):
    """El resaltado amarillo de la plantilla original es solo una guia
    visual para saber que datos cambiar por pozo: no debe quedar en el
    documento final que termina convertido a PDF."""
    output_path = tmp_path / "ldss_filled.docx"
    template_filler.fill_ldss_template(_sample_ldss_metadata(), str(output_path))

    document = docx.Document(str(output_path))
    _assert_no_highlighting_remains(document)


def test_fill_ldss_template_preserves_bloque(tmp_path):
    """Bloque no esta entre los campos que se completan: debe quedar
    exactamente igual que en la plantilla original."""
    output_path = tmp_path / "ldss_filled.docx"
    template_filler.fill_ldss_template(_sample_ldss_metadata(), str(output_path))

    document = docx.Document(str(output_path))
    texts = _all_paragraph_texts(document)
    assert "BLOQUE: 61" in texts


def test_fill_ldss_template_keeps_section_headings_intact(tmp_path):
    """Los encabezados (Heading 1/2) son los que se convierten en
    marcadores del PDF al exportar: no deben tocarse al completar los
    campos variables."""
    output_path = tmp_path / "ldss_filled.docx"
    template_filler.fill_ldss_template(_sample_ldss_metadata(), str(output_path))

    document = docx.Document(str(output_path))
    headings = [p.text for p in document.paragraphs if p.style.name.startswith("Heading")]
    assert "1. CONCILIACIÓN DE MATERIALES" in headings
    assert "CERTIFICADOS DE CALIDAD" in headings
    assert "ANEXOS" in headings


def test_fill_ldss_template_raises_clear_error_if_template_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(template_filler, "resource_path", lambda relative: tmp_path / "no_existe.docx")

    with pytest.raises(template_filler.TemplateFillError):
        template_filler.fill_ldss_template(_sample_ldss_metadata(), str(tmp_path / "out.docx"))


# -- WO CAPEX -----------------------------------------------------------------


def test_fill_wo_capex_template_substitutes_all_fields(tmp_path):
    """La plantilla WO CAPEX comparte el mismo motor de reemplazo que LDSS,
    pero con dos diferencias reales que esta prueba cubre especificamente:
    el codigo del documento va 'desnudo' (sin etiqueta 'CODIGO:') tambien
    en la portada, y el numero de reacondicionamiento en la caratula del CD
    usa la etiqueta 'CAPEX #' en vez de 'REACONDICIONAMIENTO #'."""
    metadata = _sample_wo_capex_metadata()
    output_path = tmp_path / "wo_capex_filled.docx"

    template_filler.fill_wo_capex_template(metadata, str(output_path))

    assert output_path.exists()
    document = docx.Document(str(output_path))
    texts = _all_paragraph_texts(document)

    # Portada
    assert "CONTRATO N.º: O-OTRO-CONTRATO-XYZ" in texts
    assert "88Y7777-ZZZZ-09-RDP-888-2" in texts  # codigo "desnudo"
    assert "REACONDICIONAMIENTO #19" in texts
    assert "PAD: PAD DISTINTO 9" in texts
    assert "POZO: ZZZZ-999X" in texts
    assert "LOCACIÓN: OTRA LOCACION" in texts
    assert "MARZO/2027" in texts

    # Caratula del CD (cuadros de texto)
    assert "CAPEX #19" in texts  # prefijo distinto de la portada
    assert "O-OTRO-CONTRATO-XYZ" in texts  # linea suelta del contrato


def test_fill_wo_capex_template_removes_all_highlighting(tmp_path):
    output_path = tmp_path / "wo_capex_filled.docx"
    template_filler.fill_wo_capex_template(_sample_wo_capex_metadata(), str(output_path))

    document = docx.Document(str(output_path))
    _assert_no_highlighting_remains(document)


def test_fill_wo_capex_template_preserves_bloque(tmp_path):
    output_path = tmp_path / "wo_capex_filled.docx"
    template_filler.fill_wo_capex_template(_sample_wo_capex_metadata(), str(output_path))

    document = docx.Document(str(output_path))
    texts = _all_paragraph_texts(document)
    assert "BLOQUE: 61" in texts


def test_fill_wo_capex_template_keeps_section_headings_intact(tmp_path):
    output_path = tmp_path / "wo_capex_filled.docx"
    template_filler.fill_wo_capex_template(_sample_wo_capex_metadata(), str(output_path))

    document = docx.Document(str(output_path))
    headings = [p.text for p in document.paragraphs if p.style.name.startswith("Heading")]
    assert "DOCUMENTOS INICIALES" in headings
    assert "DISEÑO BES" in headings
    assert "ANEXOS" in headings


def test_fill_wo_capex_template_raises_clear_error_if_template_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(template_filler, "resource_path", lambda relative: tmp_path / "no_existe.docx")

    with pytest.raises(template_filler.TemplateFillError):
        template_filler.fill_wo_capex_template(_sample_wo_capex_metadata(), str(tmp_path / "out.docx"))


# -- PCI ----------------------------------------------------------------------


def test_fill_pci_template_substitutes_all_fields(tmp_path):
    """PCI comparte el mismo motor de reemplazo, pero sin numero de
    reacondicionamiento/WO (es un evento unico, no repetido) y con el
    pozo citado ademas dentro del texto explicativo de un par de
    subsecciones (no solo en la caratula) -- ver
    test_fill_pci_template_substitutes_inline_pozo_mentions."""
    metadata = _sample_pci_metadata()
    output_path = tmp_path / "pci_filled.docx"

    template_filler.fill_pci_template(metadata, str(output_path))

    assert output_path.exists()
    document = docx.Document(str(output_path))
    texts = _all_paragraph_texts(document)

    assert "CONTRATO N.º: O-TEST-CONTRATO-999" in texts
    assert "77H1111-QWER-05-PCI-444-3" in texts  # codigo "desnudo" en portada
    assert "PAD: PAD PRUEBA 7" in texts
    assert "POZO: QWER-555Z" in texts
    assert "LOCACIÓN: LOCACION PRUEBA" in texts
    assert "JUNIO/2028" in texts
    assert "O-TEST-CONTRATO-999" in texts  # linea suelta del contrato en la caratula del CD


def test_fill_pci_template_substitutes_inline_pozo_mentions(tmp_path):
    """Pedido explicito del usuario: el pozo tambien aparece resaltado
    dentro de una frase, citando el nombre de otro reporte (ej. '...Pozo
    ACAR-276WIW', dentro del texto de la seccion 1.3 y 1.4), sin ninguna
    etiqueta ni ser el parrafo entero resaltado. Debe reemplazarse igual,
    sin tocar el resto de la frase."""
    output_path = tmp_path / "pci_filled.docx"
    template_filler.fill_pci_template(_sample_pci_metadata(), str(output_path))

    document = docx.Document(str(output_path))
    texts = _all_paragraph_texts(document)
    inline_mentions = [t for t in texts if "Reporte Final" in t and "Pozo" in t]
    assert len(inline_mentions) == 2
    for text in inline_mentions:
        assert "QWER-555Z" in text


def test_fill_pci_template_removes_all_highlighting(tmp_path):
    output_path = tmp_path / "pci_filled.docx"
    template_filler.fill_pci_template(_sample_pci_metadata(), str(output_path))

    document = docx.Document(str(output_path))
    _assert_no_highlighting_remains(document)


def test_fill_pci_template_preserves_bloque(tmp_path):
    output_path = tmp_path / "pci_filled.docx"
    template_filler.fill_pci_template(_sample_pci_metadata(), str(output_path))

    document = docx.Document(str(output_path))
    texts = _all_paragraph_texts(document)
    assert "BLOQUE: 61" in texts


def test_fill_pci_template_keeps_section_headings_intact(tmp_path):
    output_path = tmp_path / "pci_filled.docx"
    template_filler.fill_pci_template(_sample_pci_metadata(), str(output_path))

    document = docx.Document(str(output_path))
    headings = [p.text for p in document.paragraphs if p.style.name.startswith("Heading")]
    assert "0.- DOCUMENTOS INICIALES" in headings
    assert "1.- PERFORACIÓN" in headings
    assert "10.- ANEXOS" in headings


def test_fill_pci_template_raises_clear_error_if_template_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(template_filler, "resource_path", lambda relative: tmp_path / "no_existe.docx")

    with pytest.raises(template_filler.TemplateFillError):
        template_filler.fill_pci_template(_sample_pci_metadata(), str(tmp_path / "out.docx"))


# -- Conversion a PDF (fuera de Windows) --------------------------------------


def test_convert_docx_to_pdf_with_word_raises_clearly_outside_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(WordConversionError):
        convert_docx_to_pdf_with_word(str(tmp_path / "in.docx"), str(tmp_path / "out.pdf"))
