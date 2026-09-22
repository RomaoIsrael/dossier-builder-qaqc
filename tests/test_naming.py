from app.utils.naming import render_naming_pattern


def test_render_naming_pattern_basic():
    name = render_naming_pattern(
        "{codigo}-{pozo}-{tipo}-{revision}",
        {"codigo": "61G2158-ACAG-02-LSS-028", "pozo": "PZ1", "tipo": "QA", "revision": "0"},
    )
    assert name == "61G2158-ACAG-02-LSS-028-PZ1-QA-0"


def test_render_naming_pattern_missing_variable_becomes_empty_and_is_skipped():
    name = render_naming_pattern("{codigo}-{pozo}-{tipo}-{revision}", {"codigo": "ABC", "pozo": "PZ1"})
    # {tipo} y {revision} no estan en el contexto -> se vuelven vacios y se descartan
    # (no debe quedar "ABC-PZ1--")
    assert name == "ABC-PZ1"


def test_render_naming_pattern_sanitizes_invalid_characters():
    name = render_naming_pattern("{codigo}", {"codigo": 'A/B:C*D?"E'})
    assert "/" not in name
    assert ":" not in name
    assert "*" not in name
