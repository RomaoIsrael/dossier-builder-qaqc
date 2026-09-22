from pathlib import Path

import fitz

from app.core.flattener import FlattenOptions, flatten_pdf


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
