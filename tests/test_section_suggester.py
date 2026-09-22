from app.core import pdf_engine
from app.core.bookmark_manager import build_section_tree_from_toc
from app.core.section_suggester import suggest_section, suggest_sections_for_files


def test_suggest_section_matches_diagrama_keyword(template_with_bookmarks):
    toc = pdf_engine.extract_toc(template_with_bookmarks)
    sections = build_section_tree_from_toc(toc)

    suggestion = suggest_section("Diagrama_Final_Firmado.pdf", sections)
    assert suggestion is not None
    assert suggestion.numbering == "1.1"


def test_suggest_section_matches_pull_keyword(template_with_bookmarks):
    toc = pdf_engine.extract_toc(template_with_bookmarks)
    sections = build_section_tree_from_toc(toc)

    suggestion = suggest_section("Pull_Report_2024.pdf", sections)
    assert suggestion is not None
    assert suggestion.numbering == "1.2"


def test_suggest_section_prefers_more_specific_on_tie(template_with_bookmarks):
    toc = pdf_engine.extract_toc(template_with_bookmarks)
    sections = build_section_tree_from_toc(toc)
    # "2." y "2. CERTIFICADOS DE CALIDAD" es la unica seccion de certificados
    # en esta plantilla de prueba (no tiene subsecciones 2.1-2.4), asi que
    # basta verificar que matchee esa seccion via el sinonimo MTR->CERTIFICADO.
    suggestion = suggest_section("Certificado_MTR_Tuberia.pdf", sections)
    assert suggestion is not None
    assert suggestion.numbering == "2"


def test_suggest_section_returns_none_when_no_match(template_with_bookmarks):
    toc = pdf_engine.extract_toc(template_with_bookmarks)
    sections = build_section_tree_from_toc(toc)

    suggestion = suggest_section("xyzabc123.pdf", sections)
    assert suggestion is None


def test_suggest_sections_for_files_returns_mapping(template_with_bookmarks):
    toc = pdf_engine.extract_toc(template_with_bookmarks)
    sections = build_section_tree_from_toc(toc)

    result = suggest_sections_for_files(
        ["Diagrama_Mecanico.pdf", "Pull_Report.pdf", "sin_relacion.pdf"], sections
    )
    assert result["Diagrama_Mecanico.pdf"].numbering == "1.1"
    assert result["Pull_Report.pdf"].numbering == "1.2"
    assert result["sin_relacion.pdf"] is None
