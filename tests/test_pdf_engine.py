import fitz
import pytest

from app.core import pdf_engine


def test_get_page_count(make_pdf):
    path = make_pdf(page_count=4)
    assert pdf_engine.get_page_count(path) == 4


def test_is_pdf_readable_ok(make_pdf):
    path = make_pdf(page_count=1)
    ok, err = pdf_engine.is_pdf_readable(path)
    assert ok is True
    assert err is None


def test_is_pdf_readable_missing_file(tmp_path):
    fake_path = str(tmp_path / "no_existe.pdf")
    ok, err = pdf_engine.is_pdf_readable(fake_path)
    assert ok is False
    assert err is not None


def test_is_pdf_readable_corrupt_file(tmp_path):
    corrupt = tmp_path / "corrupto.pdf"
    corrupt.write_bytes(b"no es un pdf valido, solo bytes al azar" * 5)
    ok, err = pdf_engine.is_pdf_readable(str(corrupt))
    assert ok is False
    assert err is not None


def test_open_document_password_protected(tmp_path):
    protected_path = tmp_path / "protegido.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(protected_path), encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner123", user_pw="user123")
    doc.close()

    with pytest.raises(pdf_engine.PDFPasswordProtectedError):
        pdf_engine.open_document(str(protected_path))


def test_extract_toc_empty_when_no_bookmarks(make_pdf):
    path = make_pdf(page_count=2)
    toc = pdf_engine.extract_toc(path)
    assert toc == []


def test_insert_pdf_pages_appends_at_end(make_pdf):
    base_path = make_pdf(page_count=2, label="base")
    extra_path = make_pdf(page_count=3, label="extra")

    dest = pdf_engine.copy_document(base_path)
    inserted = pdf_engine.insert_pdf_pages(dest, extra_path, dest.page_count)

    assert inserted == 3
    assert dest.page_count == 5
    dest.close()


def test_insert_pdf_pages_in_the_middle(make_pdf):
    base_path = make_pdf(page_count=2, label="base")
    extra_path = make_pdf(page_count=1, label="extra")

    dest = pdf_engine.copy_document(base_path)
    pdf_engine.insert_pdf_pages(dest, extra_path, 1)  # despues de la primera pagina

    assert dest.page_count == 3
    text_page1 = dest[1].get_text()
    assert "extra" in text_page1
    dest.close()
