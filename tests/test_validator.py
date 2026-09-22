from app.core.validator import Severity, validate_project
from app.models.document_model import DocumentItem, SignatureTreatment
from app.models.project_model import Project
from app.models.section_model import SectionNode


def _project_with_sections(*sections: SectionNode, template_path: str) -> Project:
    project = Project(name="Proyecto de prueba", template_path=template_path)
    project.sections = list(sections)
    return project


def test_validate_project_without_template_is_error():
    project = Project(name="Sin plantilla")
    report = validate_project(project)
    assert report.has_errors is True
    assert not report.can_generate


def test_validate_project_missing_file_is_error(make_pdf):
    template = make_pdf(page_count=1)
    section = SectionNode(title="Seccion 1", numbering="1", template_page_index=0)
    section.documents.append(DocumentItem(source_path="/ruta/inexistente/archivo.pdf"))
    project = _project_with_sections(section, template_path=template)

    report = validate_project(project)
    assert report.has_errors
    assert any("no encontrado" in m.message.lower() for m in report.errors)


def test_validate_project_empty_section_is_warning(make_pdf):
    template = make_pdf(page_count=1)
    empty_section = SectionNode(title="Seccion vacia", numbering="1", template_page_index=0)
    doc_path = make_pdf(page_count=1, label="doc")
    filled_section = SectionNode(title="Seccion con documentos", numbering="2", template_page_index=1)
    filled_section.documents.append(DocumentItem(source_path=doc_path))
    project = _project_with_sections(empty_section, filled_section, template_path=template)

    report = validate_project(project)
    assert not report.has_errors
    assert any("vacia" in m.message.lower() for m in report.warnings)


def test_validate_project_ok_document_no_findings_beyond_ok(make_pdf):
    template = make_pdf(page_count=1)
    doc_path = make_pdf(page_count=2, label="doc")
    section = SectionNode(title="Seccion 1", numbering="1", template_page_index=0)
    section.documents.append(DocumentItem(source_path=doc_path, signature_treatment=SignatureTreatment.AUTO))
    project = _project_with_sections(section, template_path=template)

    report = validate_project(project)
    assert report.can_generate
    assert not report.has_errors


def test_validate_project_signed_document_warns_about_flattening(make_pdf):
    template = make_pdf(page_count=1)
    doc_path = make_pdf(page_count=1, label="firmado")
    section = SectionNode(title="Seccion 1", numbering="1", template_page_index=0)
    doc = DocumentItem(source_path=doc_path, signature_treatment=SignatureTreatment.FLATTEN)
    doc.has_signature = True
    section.documents.append(doc)
    project = _project_with_sections(section, template_path=template)

    report = validate_project(project)
    assert any("sera aplanado" in m.message.lower() for m in report.warnings)


def test_validate_project_duplicate_names_warn(make_pdf):
    template = make_pdf(page_count=1)
    doc1_path = make_pdf(page_count=1, name="repetido.pdf")
    section1 = SectionNode(title="Seccion 1", numbering="1", template_page_index=0)
    section2 = SectionNode(title="Seccion 2", numbering="2", template_page_index=1)
    section1.documents.append(DocumentItem(source_path=doc1_path, display_name="repetido.pdf"))
    section2.documents.append(DocumentItem(source_path=doc1_path, display_name="repetido.pdf"))
    project = _project_with_sections(section1, section2, template_path=template)

    report = validate_project(project)
    assert any("repetido.pdf" in m.message for m in report.warnings)


def test_validate_project_no_documents_is_error(make_pdf):
    template = make_pdf(page_count=1)
    section = SectionNode(title="Seccion 1", numbering="1", template_page_index=0)
    project = _project_with_sections(section, template_path=template)

    report = validate_project(project)
    assert any(m.severity == Severity.ERROR and "ningun documento" in m.message.lower() for m in report.errors)
