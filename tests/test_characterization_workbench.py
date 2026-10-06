from __future__ import annotations

import warnings
from pathlib import Path

import cadetgui.io.configuration_store as configuration_store
import ipywidgets as W
import pytest
from cadetgui import process_builder
from cadetgui.characterization.guide import guide_for_step
from cadetgui.characterization.parameter_store import Provenance
from cadetgui.characterization.study import Study
from cadetgui.widgets.composite import (
    CharacterizationStepWidget,
    CharacterizationWorkbenchWidget,
    ConfigurationWidget,
    InstrumentWidget,
)
from cadetgui.widgets.composite.characterization_workbench import CONFIGURATION_INTRO
from cadetgui.widgets.composite.parameter_store_view import chain_warnings

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

MANIFEST = (
    Path(__file__).parent.parent / "examples" / "data" / "characterization_akta" / "manifest.json"
)
FIXED_PANES = [
    "Setup", "System: Instrument", "System: Advanced configuration", "Measurements",
]


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Redirect the configuration store to a tmp dir -- never touch the real one."""
    monkeypatch.setattr(configuration_store, "default_store_dir", lambda: tmp_path)


@pytest.fixture(scope="module")
def example() -> CharacterizationWorkbenchWidget:
    return CharacterizationWorkbenchWidget.from_file(MANIFEST)


def _keys(wb):
    return [o[1] if isinstance(o, tuple) else o for o in wb._nav.options]


def _warnings(wb):
    return dict(zip(_keys(wb), wb._nav.tooltips))


def test_loading_and_switching_panes_build_each_recipe_once(monkeypatch):
    process_builder.clear_recipe_checks()
    calls = []
    original = process_builder.build_process

    def counting(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(process_builder, "build_process", counting)
    wb = CharacterizationWorkbenchWidget.from_file(MANIFEST)
    recipes = {process_builder.recipe_key(c.recipe, c.overrides) for c in wb.study.comparisons}
    assert len(calls) == len(recipes)

    calls.clear()
    wb.navigate("measurements")
    for name in wb.steps:
        wb.navigate("step", {"name": name})
    for target in ("parameters", "guide", "system", "setup"):
        wb.navigate(target)
    assert calls == []


def test_empty_study_builds_the_fixed_panes():
    wb = CharacterizationWorkbenchWidget()

    assert list(wb._shell.panes) == [*FIXED_PANES, "Parameters", "Guide"]
    assert _keys(wb) == [
        "Setup", "System", "Measurements", "Parameters", "Guide",
    ]
    assert wb._shell.current == "Setup"
    assert wb.steps == {}
    assert wb.comparisons.study is wb.study is wb.parameters.study is wb.setup.study


def test_default_instrument_and_configuration_are_seeded():
    wb = CharacterizationWorkbenchWidget()

    for unit in ("tubing_pre_injection", "tubing_detectors", "mixer"):
        assert unit not in wb.instrument.bypass_units()
    column = wb.configuration.process.flow_sheet.column
    assert hasattr(column, "bed_porosity")
    assert hasattr(column.binding_model, "capacity")


def test_accepts_prebuilt_instrument_and_configuration_unmodified():
    iw = InstrumentWidget()
    cw = ConfigurationWidget(instrument=iw)

    wb = CharacterizationWorkbenchWidget(instrument=iw, configuration=cw)

    assert wb.instrument is iw
    assert wb.configuration is cw
    assert wb.comparisons.configuration is cw
    assert "mixer" in wb.instrument.bypass_units()


def test_include_narrows_the_panes():
    wb = CharacterizationWorkbenchWidget(include=("Measurements", "Parameters"))

    assert list(wb._shell.panes) == ["Measurements", "Parameters"]
    assert wb.setup is wb.guide is None
    assert wb.add_step("extra") is None
    assert [s.name for s in wb.study.steps] == ["extra"]
    assert wb.steps == {}
    for target in ("setup", "system", "guide"):
        wb.navigate(target, {"unit": "column"})
    wb.navigate("step", {"name": "extra"})
    assert wb._shell.current == "Measurements"


def test_excluded_panes_are_not_constructed(monkeypatch):
    import cadetgui.widgets.composite.characterization_workbench as module

    def refuse(*_args, **_kwargs):
        raise AssertionError("an excluded pane was built")

    for name in (
        "CharacterizationSetupWidget", "ComparisonsWidget", "ParameterStoreWidget",
        "CharacterizationGuideWidget", "CharacterizationStepWidget",
    ):
        monkeypatch.setattr(module, name, refuse)

    wb = CharacterizationWorkbenchWidget(
        study=Study.load(MANIFEST), include=("System", "Advanced configuration")
    )

    assert list(wb._shell.panes) == ["System: Instrument", "System: Advanced configuration"]
    assert wb.comparisons is wb.parameters is None
    wb.add_step("extra")
    wb.study.notify()


def test_include_rejects_unknown_pane():
    with pytest.raises(ValueError, match="Not A Pane"):
        CharacterizationWorkbenchWidget(include=("Measurements", "Not A Pane"))


def test_one_step_pane_per_study_step_in_chain_order(example):
    assert list(example._shell.panes) == [
        *FIXED_PANES, "Characterization steps: Extra-column volume",
        "Characterization steps: Column packing",
        "Parameters", "Guide",
    ]
    assert list(example.steps) == ["Extra-column volume", "Column packing"]
    for name, widget in example.steps.items():
        assert isinstance(widget, CharacterizationStepWidget)
        assert widget.study is example.study
        assert example._shell.panes[f"Characterization steps: {name}"] is widget.root

    example._shell.show("Characterization steps: Column packing")
    labels = [label for label, _ in example._nav.options]
    assert labels[3:6] == ["▾ Characterization steps", "Extra-column volume", "Column packing"]


def test_example_study_flags_only_the_step_waiting_for_an_earlier_one(example):
    example._shell.show("Characterization steps: Column packing")
    warned = {key: text for key, text in _warnings(example).items() if text}
    assert list(warned) == ["Characterization steps: Column packing"]
    assert "accept Extra-column volume first" in warned["Characterization steps: Column packing"]


def test_add_step_adds_and_shows_a_pane_that_follows_renames():
    wb = CharacterizationWorkbenchWidget(study=Study.load(MANIFEST))

    widget = wb.add_step()

    assert widget.step_name == "step_3"
    assert wb._shell.current == "Characterization steps: step_3"
    assert list(wb._shell.panes)[-3:] == ["Characterization steps: step_3", "Parameters", "Guide"]
    assert "No measurements attached." in _warnings(wb)["Characterization steps: step_3"]
    with pytest.raises(ValueError, match="already exists"):
        wb.add_step("step_3")

    widget.form.name.value = "renamed"

    assert "Characterization steps: renamed" in wb._shell.panes
    assert "Characterization steps: step_3" not in wb._shell.panes
    assert wb._shell.current == "Characterization steps: renamed"
    assert wb.steps["renamed"] is widget


def test_overview_add_custom_step_opens_it_and_reports_errors():
    wb = CharacterizationWorkbenchWidget()
    setup_pane = wb.setup
    assert setup_pane._custom_step.selected_index is None
    setup_pane._new_step_name.value = "fit"
    setup_pane._btn_add_step.click()
    assert [s.name for s in wb.study.steps] == ["fit"]
    assert setup_pane._new_step_name.value == ""
    assert wb._shell.current == "Characterization steps: fit"

    setup_pane._new_step_name.value = "fit"
    setup_pane._btn_add_step.click()
    assert "already exists" in setup_pane.custom_step_status.value


def test_loading_another_study_rebuilds_the_step_panes(tmp_path):
    wb = CharacterizationWorkbenchWidget(study=Study.load(MANIFEST))
    other = Study.load(MANIFEST)
    other.steps = other.steps[1:]
    path = other.save(tmp_path / "study.json")

    wb.parameters.load_study(path)

    assert list(wb.steps) == ["Column packing"]
    assert "Characterization steps: Extra-column volume" not in wb._shell.panes


def test_comparison_problems_are_flagged():
    wb = CharacterizationWorkbenchWidget(study=Study.load(MANIFEST))
    comparison = wb.study.comparison("System pulse 1 (UV)")

    comparison.channel = "no such channel"
    wb.study.notify()

    warnings_ = _warnings(wb)
    assert "System pulse 1 (UV): Unknown channel" in warnings_["Measurements"]
    wb._shell.show("Characterization steps: Extra-column volume")
    assert "System pulse 1 (UV)" in _warnings(wb)["Characterization steps: Extra-column volume"]


def test_step_flags_missing_requirements_until_the_earlier_step_is_accepted():
    wb = CharacterizationWorkbenchWidget(study=Study.load(MANIFEST))
    wb._shell.show("Characterization steps: Extra-column volume")
    periphery, bed = wb.study.steps
    bed.requires = ("flow_sheet.tubing_pre_column.length",)
    wb.study.notify()

    warnings_ = _warnings(wb)
    periphery_pane = "Characterization steps: Extra-column volume"
    bed_pane = "Characterization steps: Column packing"
    assert warnings_[periphery_pane] == ""
    assert "accept Extra-column volume first" in warnings_[bed_pane]

    posterior = wb.study.initial_store.updated(
        {"flow_sheet.tubing_pre_column.length": 0.42}, Provenance(step="Extra-column volume"),
    )
    wb.study.accept("Extra-column volume", posterior)

    warnings_ = _warnings(wb)
    assert warnings_[periphery_pane] == ""
    assert "length (Tubing (pre column))" not in warnings_[bed_pane]


def test_parameters_pane_flags_chain_warnings():
    wb = CharacterizationWorkbenchWidget(study=Study.load(MANIFEST))
    wb.study.steps[0].requires = ("flow_sheet.column.bed_porosity",)
    wb.study.notify()

    assert "Extra-column volume" in _warnings(wb)["Parameters"]


def test_root_keeps_the_top_bar_and_header_layout():
    wb = CharacterizationWorkbenchWidget()

    assert "Characterization" in wb.root.children[1].value
    assert wb.root.children[2] is wb.configuration.workspace_header.root
    assert wb.root.children[3] is wb._shell.body


def test_navigate_shows_panes_and_highlights_the_step_on_the_system_diagram():
    wb = CharacterizationWorkbenchWidget(study=Study.load(MANIFEST))

    wb.navigate("step", {"name": "Column packing"})

    assert wb._shell.current == "Characterization steps: Column packing"
    assert set(wb.instrument._diagram._highlight) == {"column"}
    assert 'data-highlight="true"' in wb.instrument._diagram.root.value

    wb.navigate("guide")
    assert wb._shell.current == "Guide"
    with pytest.raises(ValueError, match="Unknown navigation target"):
        wb.navigate("nowhere")


def test_navigate_to_a_system_unit_expands_the_hardware_and_highlights_it():
    wb = CharacterizationWorkbenchWidget()
    wb.instrument.set_hardware_expanded(False)

    wb.navigate("system", {"unit": "tubing_pre_column"})

    assert wb._shell.current == "System: Instrument"
    assert wb.instrument.hardware_expanded
    assert set(wb.instrument._diagram._highlight) == {"tubing_pre_column"}


def _walk(widget):
    yield widget
    for child in getattr(widget, "children", ()):
        yield from _walk(child)


def _rendered_text(widget) -> str:
    """Visible text of a widget tree: HTML, labels, descriptions, options, titles."""
    parts = []
    for w in _walk(widget):
        if isinstance(w, W.HTML) and "<style" not in w.value:
            parts.append(w.value)
        for attr in ("description", "label", "placeholder"):
            if isinstance(getattr(w, attr, None), str):
                parts.append(getattr(w, attr))
        parts += [str(o[0] if isinstance(o, tuple) else o) for o in getattr(w, "options", ())]
        parts += list(getattr(w, "option_labels", ()))
        parts += list(getattr(w, "columns", ()) or ())
        parts += [str(t) for t in getattr(w, "titles", ()) or ()]
    return " ".join(parts)


def test_no_stage_wording_in_overview_guide_and_steps(example):
    panes = [example.setup.root, example.guide.root, example.comparisons.root]
    panes += [w.root for w in example.steps.values()]
    for root in panes:
        text = _rendered_text(root).lower()
        assert "stage" not in text
        assert "fit step" not in text


def test_navigate_to_measurements_starts_one_of_the_experiment_type():
    wb = CharacterizationWorkbenchWidget()

    wb.navigate("measurements", {"experiment_type": "system_pulse"})

    assert wb._shell.current == "Measurements"
    assert wb.comparisons._flow.is_open
    assert wb.comparisons._flow.experiment_type.id == "system_pulse"


def _protein_pulse(study, name="Protein pulse 1"):
    import dataclasses

    large = study.comparison("Large tracer pulse 1 (UV)")
    return dataclasses.replace(large, name=name, experiment_type="nonbinding_protein_pulse")


def test_overview_buttons_navigate_and_set_up_steps():
    wb = CharacterizationWorkbenchWidget(study=Study.load(MANIFEST))

    wb.setup.buttons["system_periphery"].click()
    assert wb._shell.current == "Characterization steps: Extra-column volume"

    wb.navigate("setup")
    wb.setup.buttons["particle_transport"].click()
    assert wb._shell.current == "Measurements"

    wb.study.upsert_comparison(_protein_pulse(wb.study))
    wb.navigate("setup")
    wb.setup.buttons["particle_transport"].click()

    assert [s.name for s in wb.study.steps][-1] == "Particle transport"
    assert wb._shell.current == "Characterization steps: Particle transport"


def test_fitted_steps_reach_the_overview():
    wb = CharacterizationWorkbenchWidget(study=Study.load(MANIFEST))
    wb.steps["Extra-column volume"].results.result = object()

    assert wb.fitted_steps == {"Extra-column volume"}
    wb.navigate("setup")
    assert wb.setup.statuses["Extra-column volume"].fitted


def test_overview_system_card_follows_the_configuration_and_opens_the_system_pane():
    wb = CharacterizationWorkbenchWidget(study=Study.load(MANIFEST))

    assert wb.setup._system_card.children
    wb.setup.buttons["system"].click()
    assert wb._shell.current == "System: Instrument"


def test_step_names_with_spaces_round_trip(tmp_path):
    wb = CharacterizationWorkbenchWidget(study=Study.load(MANIFEST))
    study = wb.study
    posterior = study.initial_store.updated(
        {"flow_sheet.tubing_pre_column.length": 0.42}, Provenance(step="Extra-column volume"),
    )
    study.accept("Extra-column volume", posterior)

    assert "Characterization steps: Extra-column volume" in wb._shell.panes
    wb.navigate("step", {"name": "Column packing"})
    assert wb._shell.current == "Characterization steps: Column packing"
    assert chain_warnings(study) == []
    assert study.prior_for("Column packing") is posterior

    reloaded = Study.load(study.save(tmp_path / "study.json"))
    assert [s.name for s in reloaded.steps] == ["Extra-column volume", "Column packing"]
    stored = reloaded.posteriors["Extra-column volume"]
    assert stored.entries["flow_sheet.tubing_pre_column.length"].provenance.step == (
        "Extra-column volume"
    )
    assert guide_for_step(reloaded.steps[0]).id == "system_periphery"
    assert guide_for_step(reloaded.steps[1]).id == "column_packing"


def _add_measurement(wb, file_name, channel, type_id, component):
    flow = wb.comparisons._flow
    wb.comparisons.start_add()
    flow.load_bytes(file_name, (MANIFEST.parent / file_name).read_bytes())
    flow.next()
    flow._channel.value = channel
    flow.next()
    flow._type_table.value = type_id
    flow.next()
    if component in [value for _, value in flow._component._options]:
        flow._component.value = component
    else:
        flow.new_component(component)
    return flow


def test_advanced_configuration_hides_the_process_template_but_still_snapshots():
    wb = CharacterizationWorkbenchWidget()
    configuration = wb.configuration

    assert configuration._process_section.layout.display == "none"
    assert configuration._column_form is not None and configuration._binding_form is not None
    assert any(CONFIGURATION_INTRO in getattr(c, "value", "") for c in configuration.root.children)
    assert configuration.snapshot().template_key == "Pulse Injection"
    assert _warnings(wb)["System"] == ""

    wb.instrument._sample_loop_checkbox.value = False
    assert configuration.snapshot().instrument.include_sample_loop is False
    assert _warnings(wb)["System"] == ""

    flow = _add_measurement(wb, "system_pulse_1_uv.csv", "UV 1_280", "system_pulse", "Acetone")
    flow.next()
    assert "System setup" in flow._base_note.value
    added = flow.confirm()
    assert added.recipe.template_key == "Pulse Injection"
    assert added.recipe.instrument.include_sample_loop is True
    assert added.problems() == []


def test_flow_rate_on_the_system_pane_feeds_the_base_recipe_and_the_add_flow():
    wb = CharacterizationWorkbenchWidget()
    ml_per_min = 1e-6 / 60

    assert wb.flow_rate.field.value == "1"
    children = list(wb.instrument.root.children)
    flow_section = wb.flow_rate.root
    components = children.index(wb.instrument._components_section)
    assert children.index(flow_section) == components + 1
    assert children.index(flow_section) < children.index(wb.instrument._flow_path_section)
    wb.flow_rate.field.value = "0.5"
    recipe = wb.configuration.snapshot()
    assert recipe.model_values["flow_rate"] == pytest.approx(0.5 * ml_per_min)
    wb.navigate("setup")
    assert "0.5 mL/min" in wb.setup._system_card.children[0].children[1].value

    flow = _add_measurement(
        wb, "system_pulse_1_uv.csv", "UV 1_280", "linear_gradient_elution", "Protein"
    )
    assert flow._flow_rate.value == "0.5"
    added = flow.confirm()
    assert added.resolved_flow_rate == pytest.approx(0.5 * ml_per_min)
    assert added.recipe.model_values["flow_rate_wash"] == pytest.approx(0.5 * ml_per_min)

    wb.flow_rate.field.value = "abc"
    assert wb.configuration.flow_rate == pytest.approx(0.5 * ml_per_min)


def test_applying_the_configuration_keeps_the_measurements_own_method():
    wb = CharacterizationWorkbenchWidget(study=Study.load(MANIFEST))
    name = "Large tracer pulse 1 (UV)"
    wb.comparisons.select(name)
    before = wb.study.comparison(name).recipe
    wb.instrument._unit_checkboxes["tubing_post_column"].value = True
    wb.configuration.column_form.element("length").value = 0.123

    wb.comparisons._recipe_source.value = "__configuration__"
    wb.comparisons._on_use_recipe(None)

    after = wb.study.comparison(name).recipe
    assert after.template_key == before.template_key
    assert after.model_values == before.model_values
    assert after.components == before.components
    assert after.instrument.bypass_units == before.instrument.bypass_units
    assert after.column_values["length"] == 0.123
    assert wb.study.comparison(name).problems() == []


def test_setup_is_fresh_on_the_first_sidebar_click_after_adding_a_measurement():
    wb = CharacterizationWorkbenchWidget()

    def click(label):
        wb._nav.index = _keys(wb).index(label)

    click("Measurements")
    flow = _add_measurement(
        wb, "system_pulse_1_uv.csv", "UV 1_280", "system_pulse", "Acetone"
    )
    flow.confirm()
    click("Setup")

    assert wb._shell.current == "Setup"
    assert wb.setup.buttons["system_periphery"].description.startswith("Set up this step")
