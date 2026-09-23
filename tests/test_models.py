from app.models.document_model import DocumentItem, DocumentStatus, SignatureTreatment
from app.models.project_model import Project
from app.models.section_model import SectionNode


def test_document_item_round_trip():
    doc = DocumentItem(
        source_path="/tmp/a.pdf",
        display_name="a.pdf",
        signature_treatment=SignatureTreatment.FLATTEN,
        has_signature=True,
        status=DocumentStatus.FLATTENED,
        page_count=3,
    )
    restored = DocumentItem.from_dict(doc.to_dict())
    assert restored.source_path == doc.source_path
    assert restored.signature_treatment == SignatureTreatment.FLATTEN
    assert restored.status == DocumentStatus.FLATTENED
    assert restored.has_signature is True
    assert restored.page_count == 3


def test_section_node_round_trip_with_children_and_documents():
    child = SectionNode(title="Subseccion", numbering="1.1", level=2, template_page_index=3)
    child.documents.append(DocumentItem(source_path="/tmp/x.pdf"))
    parent = SectionNode(title="Seccion", numbering="1", level=1, template_page_index=2)
    parent.children.append(child)

    restored = SectionNode.from_dict(parent.to_dict())
    assert restored.title == "Seccion"
    assert len(restored.children) == 1
    assert restored.children[0].title == "Subseccion"
    assert len(restored.children[0].documents) == 1
    assert restored.children[0].documents[0].source_path == "/tmp/x.pdf"


def test_project_round_trip_preserves_structure():
    section = SectionNode(title="Seccion", numbering="1", level=1, template_page_index=0)
    section.documents.append(DocumentItem(source_path="/tmp/doc.pdf"))

    project = Project(name="Proyecto X", template_path="/tmp/plantilla.pdf")
    project.sections = [section]
    project.metadata.pozo = "PZ-1"
    project.settings.flatten_dpi = 200

    restored = Project.from_dict(project.to_dict())
    assert restored.name == "Proyecto X"
    assert restored.metadata.pozo == "PZ-1"
    assert restored.settings.flatten_dpi == 200
    assert restored.total_documents() == 1
    assert restored.find_section(section.id) is not None


def test_project_round_trip_preserves_generation_tracking():
    project = Project(name="Proyecto Y")
    assert project.generation_count == 0
    assert project.last_output_filename == ""

    project.generation_count = 3
    project.last_output_filename = "CODIGO-POZO-TIPO-2.pdf"
    project.last_generated_at = "2026-09-23T10:00:00+00:00"

    restored = Project.from_dict(project.to_dict())
    assert restored.generation_count == 3
    assert restored.last_output_filename == "CODIGO-POZO-TIPO-2.pdf"
    assert restored.last_generated_at == "2026-09-23T10:00:00+00:00"
