from app.core.project import ProjectError, ProjectService
from app.models.document_model import DocumentItem
from app.models.section_model import SectionNode
from app.services.database import DatabaseService


def _service(tmp_path) -> ProjectService:
    return ProjectService(database=DatabaseService(db_path=tmp_path / "index.sqlite3"))


def test_save_and_open_round_trip(tmp_path):
    service = _service(tmp_path)
    project = service.new_project("Proyecto de prueba")
    project.template_path = "/tmp/plantilla.pdf"
    section = SectionNode(title="Seccion 1", numbering="1", template_page_index=0)
    section.documents.append(DocumentItem(source_path="/tmp/doc.pdf"))
    project.sections = [section]

    saved_path = service.save(project, str(tmp_path / "mi_proyecto"))
    assert saved_path.suffix == ".dossierproj"
    assert saved_path.exists()

    reopened = service.open(str(saved_path))
    assert reopened.name == "Proyecto de prueba"
    assert reopened.template_path == "/tmp/plantilla.pdf"
    assert reopened.total_documents() == 1
    assert reopened.project_file_path == str(saved_path)


def test_open_missing_file_raises_project_error(tmp_path):
    service = _service(tmp_path)
    try:
        service.open(str(tmp_path / "no_existe.dossierproj"))
        assert False, "deberia haber lanzado ProjectError"
    except ProjectError:
        pass


def test_open_corrupt_project_file_raises_project_error(tmp_path):
    service = _service(tmp_path)
    bad_file = tmp_path / "corrupto.dossierproj"
    bad_file.write_text("esto no es json valido {{{")
    try:
        service.open(str(bad_file))
        assert False, "deberia haber lanzado ProjectError"
    except ProjectError:
        pass


def test_duplicate_project_creates_independent_copy(tmp_path):
    service = _service(tmp_path)
    project = service.new_project("Original")
    service.save(project, str(tmp_path / "original"))

    clone = service.duplicate(project, str(tmp_path / "clonado"), new_name="Clon")
    assert clone.id != project.id
    assert clone.name == "Clon"
    assert (tmp_path / "clonado.dossierproj").exists()
