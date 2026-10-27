from pathlib import Path
from unittest.mock import patch

import fitz

from app.core.flattener import FlattenError, FlattenOptions, flatten_pdf


def test_flatten_preserves_page_count_and_size(make_pdf, tmp_path):
    source = make_pdf(page_count=3, label="firmado")
    output = str(tmp_path / "flat.pdf")

    flatten_pdf(source, output, FlattenOptions(dpi=150, image_format="jpeg"))

    assert Path(output).exists()
    src_doc = fitz.open(source)
    out_doc = fitz.open(output)
    try:
        assert out_doc.page_count == src_doc.page_count
        for i in range(src_doc.page_count):
            assert abs(out_doc[i].rect.width - src_doc[i].rect.width) < 0.5
            assert abs(out_doc[i].rect.height - src_doc[i].rect.height) < 0.5
    finally:
        src_doc.close()
        out_doc.close()


def test_flatten_removes_original_text_layer(make_pdf, tmp_path):
    """Una pagina aplanada ya no debe contener texto seleccionable (todo es imagen)."""
    source = make_pdf(page_count=1, label="CONTENIDO_ORIGINAL_UNICO")
    output = str(tmp_path / "flat.pdf")

    flatten_pdf(source, output, FlattenOptions(dpi=150))

    out_doc = fitz.open(output)
    try:
        text = out_doc[0].get_text()
    finally:
        out_doc.close()
    assert "CONTENIDO_ORIGINAL_UNICO" not in text


def test_flatten_handles_rotated_pages(tmp_path):
    source_path = tmp_path / "rotada.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((40, 60), "pagina rotada")
    page.set_rotation(90)
    doc.save(str(source_path))
    doc.close()

    output = str(tmp_path / "flat_rotada.pdf")
    flatten_pdf(str(source_path), output, FlattenOptions(dpi=100))

    out_doc = fitz.open(output)
    try:
        # Al rotar 90 grados, el ancho/alto visual de la pagina de salida
        # debe quedar intercambiado respecto al mediabox original (595x842).
        assert out_doc[0].rect.width == 842
        assert out_doc[0].rect.height == 595
    finally:
        out_doc.close()


def test_flatten_retries_at_lower_dpi_when_image_too_large(make_pdf, tmp_path):
    """Regresion: si MuPDF rechaza una imagen por 'Overly large image' (un
    limite de seguridad de la libreria, no un error del archivo), aplanar
    debe reintentar automaticamente a una resolucion menor en vez de hacer
    fallar toda la generacion del dossier."""
    source = make_pdf(page_count=1, label="firmado")
    output = str(tmp_path / "flat.pdf")

    original_get_pixmap = fitz.Page.get_pixmap
    calls = {"count": 0}

    def flaky_get_pixmap(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("code=5: Overly large image")
        return original_get_pixmap(self, *args, **kwargs)

    with patch.object(fitz.Page, "get_pixmap", flaky_get_pixmap):
        flatten_pdf(source, output, FlattenOptions(dpi=450))

    assert Path(output).exists()
    assert calls["count"] >= 2


def test_flatten_raises_if_every_dpi_fallback_also_fails(make_pdf, tmp_path):
    source = make_pdf(page_count=1, label="firmado")
    output = str(tmp_path / "flat.pdf")

    def always_too_large(self, *args, **kwargs):
        raise RuntimeError("code=5: Overly large image")

    with patch.object(fitz.Page, "get_pixmap", always_too_large):
        try:
            flatten_pdf(source, output, FlattenOptions(dpi=450))
            assert False, "deberia haber lanzado FlattenError"
        except FlattenError:
            pass
    assert not Path(output).exists()


def test_flatten_does_not_retry_on_unrelated_errors(make_pdf, tmp_path):
    """Un error que no sea de 'imagen demasiado grande' (ej. archivo
    corrupto) no debe generar reintentos inutiles a menor resolucion: debe
    fallar de inmediato con el error real, en un solo intento."""
    source = make_pdf(page_count=1, label="firmado")
    output = str(tmp_path / "flat.pdf")

    calls = {"count": 0}

    def unrelated_error(self, *args, **kwargs):
        calls["count"] += 1
        raise RuntimeError("some other unrelated mupdf error")

    with patch.object(fitz.Page, "get_pixmap", unrelated_error):
        try:
            flatten_pdf(source, output, FlattenOptions(dpi=450))
            assert False, "deberia haber lanzado FlattenError"
        except FlattenError:
            pass
    assert calls["count"] == 1
