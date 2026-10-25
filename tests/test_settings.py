from app.services.settings import AppSettings


def test_recent_projects_migrates_plain_paths_to_dicts_with_opened_at():
    # Formato viejo (antes de que existiera la fecha/hora): lista de rutas.
    data = {"recent_projects": ["C:/pozo1.dossierproj", "C:/pozo2.dossierproj"]}

    settings = AppSettings.from_dict(data)

    assert settings.recent_projects == [
        {"path": "C:/pozo1.dossierproj", "opened_at": None},
        {"path": "C:/pozo2.dossierproj", "opened_at": None},
    ]


def test_recent_projects_keeps_dicts_with_opened_at():
    data = {
        "recent_projects": [
            {"path": "C:/pozo1.dossierproj", "opened_at": "2026-10-01T10:00:00+00:00"},
        ]
    }

    settings = AppSettings.from_dict(data)

    assert settings.recent_projects == [
        {"path": "C:/pozo1.dossierproj", "opened_at": "2026-10-01T10:00:00+00:00"},
    ]


def test_recent_projects_round_trip():
    settings = AppSettings()
    settings.recent_projects = [{"path": "C:/pozo1.dossierproj", "opened_at": "2026-10-01T10:00:00+00:00"}]

    restored = AppSettings.from_dict(settings.to_dict())

    assert restored.recent_projects == settings.recent_projects
