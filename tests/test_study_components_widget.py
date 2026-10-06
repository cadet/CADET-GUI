from __future__ import annotations

import warnings
from pathlib import Path

import cadetgui.io.configuration_store as configuration_store
import pytest
from cadetgui.characterization.study import Study, StudyComponent
from cadetgui.widgets.composite import (
    CharacterizationWorkbenchWidget,
    ComparisonsWidget,
    ConfigurationWidget,
    InstrumentWidget,
    StudyComponentsWidget,
)
from cadetgui.widgets.composite.characterization_setup import (
    CharacterizationSetupWidget,
)

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

MANIFEST = (
    Path(__file__).parent.parent / "examples" / "data" / "characterization_akta" / "manifest.json"
)
EXAMPLE = ["SystemTracer", "SmallTracer", "LargeTracer"]


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(configuration_store, "default_store_dir", lambda: tmp_path)


@pytest.fixture
def study() -> Study:
    return Study.load(MANIFEST)


def _to_details(widget, file_name, type_id):
    flow = widget._flow
    widget.start_add()
    flow.load_bytes(file_name, (MANIFEST.parent / file_name).read_bytes())
    flow.next()
    flow.next()
    flow._type_table.value = type_id
    flow.next()
    assert flow.page == 3
    return flow


def test_editor_lists_components_and_adds_one(study):
    editor = StudyComponentsWidget(study)
    assert list(editor.rows) == EXAMPLE
    text, role, remove = editor.rows["SmallTracer"]
    assert role.value == "small tracer" and remove.disabled
    assert "used by 2 measurements" in editor._rows_box.children[1].children[3].value
    assert "What goes here?" in editor.root.children[2].value

    assert editor.add("IgG", "protein")
    assert study.component("IgG") == StudyComponent("IgG", "protein")
    assert not editor.rows["IgG"][2].disabled
    assert not editor.add("IgG", "protein")
    assert "already declared" in editor.status.value


def test_editor_renames_changes_roles_and_removes(study):
    editor = StudyComponentsWidget(study)
    editor.add("IgGG", "protein")
    editor.rows["IgGG"][0].value = "IgG"
    assert study.component("IgG") is not None and "IgG" in editor.rows

    editor.rows["SmallTracer"][0].value = "Acetone"
    assert "cannot be renamed" in editor.status.value
    assert editor.rows["SmallTracer"][0].value == "SmallTracer"

    editor.rows["IgG"][1].value = "large tracer"
    assert study.component("IgG").role == "large tracer"

    editor.rows["IgG"][2].click()
    assert study.component("IgG") is None and "IgG" not in editor.rows


def test_salt_row_is_fixed(study):
    study.add_component("Salt", "salt")
    editor = StudyComponentsWidget(study)
    text, role, _ = editor.rows["Salt"]
    assert text.disabled and role.disabled


def test_system_pane_edits_components_with_roles_above_the_hardware(study):
    wb = CharacterizationWorkbenchWidget(study=study)
    assert wb._shell.panes["System: Instrument"] is wb.instrument.root
    assert wb.components is wb.instrument.study_components
    children = list(wb.instrument.root.children)
    section = wb.instrument._components_section
    assert children.index(section) < children.index(wb.instrument._diagram.root)
    assert children.index(section) < children.index(wb.instrument._flow_path_section)
    assert wb.components.root in section.children
    assert list(wb.components.rows) == EXAMPLE


def test_workbench_components_follow_the_study(study):
    wb = CharacterizationWorkbenchWidget(study=study)
    assert wb.instrument.components == EXAMPLE
    assert wb.configuration.components == EXAMPLE
    assert wb.configuration._components_section.layout.display == "none"

    study.add_component("IgG", "protein")
    assert wb.configuration.components == [*EXAMPLE, "IgG"]
    study.add_component("Salt", "salt")
    assert wb.instrument.components[0] == "Salt"
    assert wb.configuration.components[0] == "Salt"


def test_roles_only_when_a_study_is_bound(study):
    iw = InstrumentWidget()
    assert iw.study_components is None
    assert iw._components_field in iw._components_section.children

    iw.bind_study(study)
    assert iw._components_field not in iw._components_section.children
    assert iw.study_components.rows["SmallTracer"][1].value == "small tracer"
    assert iw.components == EXAMPLE


def test_standalone_configuration_keeps_its_component_editor():
    cw = ConfigurationWidget()
    assert cw._components_section.layout.display != "none"
    bound = ConfigurationWidget(instrument=InstrumentWidget())
    assert bound._components_section.layout.display == "none"


def test_add_flow_offers_only_fitting_components(study):
    widget = ComparisonsWidget(study)
    flow = _to_details(widget, "system_pulse_1_uv.csv", "system_pulse")
    assert flow._component.option_labels == [
        "SystemTracer (system tracer)", "SmallTracer (small tracer)",
        "LargeTracer (large tracer — not a small tracer or system tracer)", "New component…",
    ]
    assert flow._component.value == "SystemTracer"
    assert flow._new_component.layout.display == "none"


def test_add_flow_declares_a_new_component_with_the_types_role(study):
    widget = ComparisonsWidget(study)
    flow = _to_details(widget, "large_tracer_pulse_1_uv.csv", "nonbinding_protein_pulse")
    assert flow._component.option_labels == [
        "SystemTracer (system tracer — not a protein)",
        "SmallTracer (small tracer — not a protein)",
        "LargeTracer (large tracer — not a protein)",
        "New component…",
    ]
    assert flow._component.value == "__new__"
    assert flow._new_component.layout.display == ""
    assert "a protein" in flow._component_note.value
    assert flow._new_role.value == "protein"

    flow.next()
    assert flow.page == 3 and "New component" in flow.status.value

    flow.new_component("SmallTracer")
    assert "already declared as small tracer" in flow._new_component.error
    flow.new_component("IgG")
    flow.next()
    added = flow.confirm()
    assert added.probe == "IgG"
    assert study.component("IgG") == StudyComponent("IgG", "protein")
    assert study.measurement_problems(added) == []
    assert "Declared IgG (protein)" in widget.status.value

    flow = _to_details(widget, "large_tracer_pulse_2_uv.csv", "nonbinding_protein_pulse")
    assert flow._component.option_labels[0] == "IgG (protein)"
    assert flow._component.option_labels[-1] == "New component…"
    assert flow._component.value == "IgG"


def test_advanced_editor_picks_a_declared_component(study):
    widget = ComparisonsWidget(study)
    widget.select("Small tracer pulse 1 (conductivity)")
    assert widget._probe.option_labels[:2] == ["None", "SmallTracer (small tracer)"]
    assert "SystemTracer (system tracer — not a small tracer)" in widget._probe.option_labels

    study.add_component("Acetone", "small tracer")
    assert "Acetone (small tracer)" in widget._probe.option_labels
    widget._probe.value = "Acetone"
    edited = study.comparison("Small tracer pulse 1 (conductivity)")
    assert edited.probe == "Acetone"
    assert edited.recipe.components == ["Acetone"] and edited.components == ["Acetone"]
    assert list(widget._component_fields) == ["Acetone"]

    study.set_component_role("Acetone", "protein")
    assert "Acetone (protein — not a small tracer)" in widget._probe.option_labels
    assert "declared as a protein" in widget._problems_html.value
    assert "System → Components" in widget._problems_html.value


def test_overview_system_card_lists_the_components(study):
    recipe = study.comparisons[0].recipe
    setup_pane = CharacterizationSetupWidget(study, system=lambda: recipe)

    def card():
        return setup_pane._system_card.children[0].children[1].value

    assert "<td><b>SmallTracer</b></td>" in card()
    assert "small tracer</span></td><td>2</td>" in card()
    assert "Names link the steps" not in card()

    study.add_component("IgG", "protein")
    assert "<td><b>IgG</b></td>" in card()


def test_step_header_names_the_components(study):
    from cadetgui.widgets.composite import CharacterizationStepWidget

    widget = CharacterizationStepWidget(study, "Column packing")
    assert "SmallTracer (small tracer), LargeTracer (large tracer)" in widget.header.value


def test_role_selectors_are_styled_dropdowns(study):
    from cadetgui.widgets._chrome import style_tag
    from cadetgui.widgets.elements import ChoiceField

    editor = StudyComponentsWidget(study)
    selectors = [row[1] for row in editor.rows.values()] + [editor._new_role]
    assert all("cadetgui-select" in s._dom_classes for s in selectors)
    css = style_tag()
    chevron = css[css.index(".cadetgui-select select:not([multiple]):not([size]) {"):]
    chevron = chevron[:chevron.index("}")]
    assert "appearance: none" in chevron and "linear-gradient" in chevron
    assert ".cadetgui-select select:hover:not(:disabled)" in css
    field_css = ChoiceField._css
    rule = field_css[field_css.index(".cadetgui-field-select {"):]
    assert "appearance: none" in rule[:rule.index("}")]


def test_salt_row_name_is_read_only_with_a_note(study):
    study.add_component("Salt", "salt")
    editor = StudyComponentsWidget(study)
    row = editor._rows_box.children[0]
    assert row.children[0].value == "Salt" and row.children[0].disabled
    assert "fixed name, required by the binding model" in row.children[3].value


def test_add_row_salt_role_locks_the_name(study):
    editor = StudyComponentsWidget(study)
    editor._new_name.value = "NaCl"
    editor._new_role.value = "salt"
    assert editor._new_name.value == "Salt" and editor._new_name.disabled
    assert "fixed name" in editor._role_help.value
    editor._new_role.value = "protein"
    assert editor._new_name.value == "" and not editor._new_name.disabled
    editor._new_role.value = "salt"
    editor._btn_add.click()
    assert study.component("Salt").role == "salt"
    assert "salt" not in list(editor._new_role.options)
    assert not editor._new_name.disabled
    assert "Salt is already declared" in editor._role_help.value


def test_role_change_to_salt_is_refused_for_other_names(study):
    editor = StudyComponentsWidget(study)
    editor.rows["SmallTracer"][1].value = "salt"
    assert study.component("SmallTracer").role == "small tracer"
    assert editor.rows["SmallTracer"][1].value == "small tracer"
    assert "only the component named Salt" in editor.status.value
    assert "add Salt with the salt role" in editor.status.value
