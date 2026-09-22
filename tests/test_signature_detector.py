import fitz

from app.core.signature_detector import detect_signatures


def test_no_signature_detected_on_plain_pdf(make_pdf):
    path = make_pdf(page_count=1, label="documento normal")
    info = detect_signatures(path)
    assert info.has_signature is False
    assert info.signature_count == 0


def test_signature_widget_is_detected(tmp_path):
    path = tmp_path / "con_firma.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)

    widget = fitz.Widget()
    widget.field_name = "Firma1"
    widget.field_type = fitz.PDF_WIDGET_TYPE_SIGNATURE
    widget.rect = fitz.Rect(50, 50, 200, 100)
    page.add_widget(widget)

    doc.save(str(path))
    doc.close()

    info = detect_signatures(str(path))
    assert info.has_signature is True
    assert info.signature_count >= 1


def test_detect_signatures_on_corrupt_file_does_not_raise(tmp_path):
    bad = tmp_path / "malo.pdf"
    bad.write_bytes(b"contenido invalido")
    info = detect_signatures(str(bad))
    assert info.has_signature is False
