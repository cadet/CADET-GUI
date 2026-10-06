from cadetgui.characterization.guide import GLOSSARY
from cadetgui.widgets._help import checklist_html, info_box_html, term_html


def test_known_term_carries_its_definition_as_tip():
    term = next(iter(GLOSSARY))
    out = term_html(term, label="x")
    assert "cadetgui-term" in out
    assert ">x</span>" in out
    assert "data-tip=" in out


def test_unknown_term_is_plain_escaped_text():
    assert term_html("<nope>") == "&lt;nope&gt;"


def test_info_box_and_checklist_escape_text():
    box = info_box_html("A & B", "<b>body</b>", open=True)
    assert "<details class='cadetgui-info' open>" in box
    assert "A &amp; B" in box and "<b>body</b>" in box
    assert "<li>1 &lt; 2</li>" in checklist_html(["1 < 2"])


def test_determines_table_has_one_row_per_parameter():
    from cadetgui.characterization.guide import CHAIN_BY_ID
    from cadetgui.widgets._help import determines_table_html

    guide = CHAIN_BY_ID["column_packing"]
    out = determines_table_html(guide.determines)
    assert out.count("<tr>") == len(guide.determines) + 1
    assert "<th>Unit</th>" in out and "Bed porosity" in out and "m²/s" in out


def test_experiments_table_lists_attached_measurements_or_none_yet():
    from cadetgui.characterization.guide import CHAIN_BY_ID
    from cadetgui.widgets._help import experiments_table_html

    types = CHAIN_BY_ID["column_packing"].experiment_types
    out = experiments_table_html(types, {types[0]: ["Small tracer pulse 1 (conductivity)"]})
    assert "<th>Measurements</th>" in out
    assert "Small tracer pulse 1 (conductivity)" in out and "none yet" in out
    assert "<th>Measurements</th>" not in experiments_table_html(types)
