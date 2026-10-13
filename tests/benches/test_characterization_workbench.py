"""CharacterizationWorkbenchWidget: panes over one Study, navigation and sidebar warnings."""
from __future__ import annotations

import dataclasses

import cadetgui.widgets.benches.characterization as bench_module
import pytest
from cadetgui.characterization.parameter_store import Provenance
from cadetgui.characterization.study import Study
from cadetgui.instrument import process_builder
from cadetgui.widgets.benches import CharacterizationWorkbenchWidget
from cadetgui.widgets.characterization import CharacterizationStepWidget
from cadetgui.widgets.instrument import ConfigurationWidget, InstrumentWidget

from characterization.synthetic import MANIFEST, data_bytes

STEP = "Characterization steps: "
FIXED_PANES = ["Setup", "System: Instrument", "System: Advanced configuration", "Measurements"]
EXAMPLE = ["SystemTracer", "SmallTracer", "LargeTracer"]
ML_PER_MIN = 1e-6 / 60


@pytest.fixture
def study() -> Study:
    return Study.load(MANIFEST)


@pytest.fixture
def example(study) -> CharacterizationWorkbenchWidget:
    return CharacterizationWorkbenchWidget(study=study)


def nav_keys(wb):
    return [o[1] if isinstance(o, tuple) else o for o in wb._nav.options]


def warnings_of(wb):
    return dict(zip(nav_keys(wb), wb._nav.tooltips))


def add_measurement(wb, file_name, type_id, component):
    flow = wb.comparisons._flow
    wb.comparisons.start_add()
    flow.load_bytes(file_name, data_bytes(file_name))
    flow.next()
    flow.next()
    flow._type_table.value = type_id
    flow.next()
    flow.new_component(component)
    return flow


def test_an_empty_workbench_shares_one_study_and_seeds_the_system():
    wb = CharacterizationWorkbenchWidget()
    notified = []
    wb.add_listener(lambda: notified.append(1))

    assert list(wb._shell.panes) == [*FIXED_PANES, "Parameters", "Guide"]
    assert wb._shell.current == "Setup" and wb.steps == {}
    assert wb.comparisons.study is wb.study is wb.parameters.study is wb.setup.study
    assert not {"tubing_pre_injection", "tubing_detectors", "mixer"} & set(
        wb.instrument.bypass_units()
    )
    column = wb.configuration.process.flow_sheet.column
    assert hasattr(column, "bed_porosity") and hasattr(column.binding_model, "capacity")
    assert wb.configuration._process_section.layout.display == "none"
    assert wb.configuration.snapshot().template_key == "Pulse Injection"

    wb.study.add_component("Salt", "salt")
    assert wb.instrument.components[0] == wb.configuration.components[0] == "Salt"
    assert notified

    wb.setup._new_step_name.value = "fit"
    wb.setup._btn_add_step.click()
    assert [s.name for s in wb.study.steps] == ["fit"]
    assert wb._shell.current == f"{STEP}fit"
    wb.setup._new_step_name.value = "fit"
    wb.setup._btn_add_step.click()
    assert "already exists" in wb.setup.custom_step_status.value


def test_prebuilt_instrument_and_configuration_are_only_bound():
    instrument = InstrumentWidget()
    configuration = ConfigurationWidget(instrument=instrument)
    wb = CharacterizationWorkbenchWidget(instrument=instrument, configuration=configuration)
    assert wb.instrument is instrument and wb.configuration is configuration
    assert wb.comparisons.configuration is configuration
    assert "mixer" in wb.instrument.bypass_units()


def test_include_builds_only_the_named_panes(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("an excluded pane was built")

    for name in ("CharacterizationSetupWidget", "CharacterizationGuideWidget",
                 "CharacterizationStepWidget"):
        monkeypatch.setattr(bench_module, name, refuse)
    with pytest.raises(ValueError, match="Not A Pane"):
        CharacterizationWorkbenchWidget(include=("Measurements", "Not A Pane"))

    wb = CharacterizationWorkbenchWidget(include=("Measurements", "Parameters"))

    assert list(wb._shell.panes) == ["Measurements", "Parameters"]
    assert wb.setup is wb.guide is None
    assert wb.add_step("extra") is None and wb.steps == {}
    for target in ("setup", "system", "guide"):
        wb.navigate(target, {"unit": "column"})
    wb.navigate("step", {"name": "extra"})
    assert wb._shell.current == "Measurements"


def test_the_example_builds_each_recipe_once_with_one_pane_per_step(monkeypatch):
    process_builder.clear_recipe_checks()
    calls = []
    original = process_builder.build_process
    monkeypatch.setattr(process_builder, "build_process",
                        lambda *a, **k: calls.append(a) or original(*a, **k))

    wb = CharacterizationWorkbenchWidget.from_file(MANIFEST)

    recipes = {process_builder.recipe_key(c.recipe, c.overrides) for c in wb.study.comparisons}
    assert len(calls) == len(recipes)
    assert list(wb._shell.panes) == [
        *FIXED_PANES, f"{STEP}Extra-column volume", f"{STEP}Column packing",
        "Parameters", "Guide",
    ]
    for name, widget in wb.steps.items():
        assert isinstance(widget, CharacterizationStepWidget)
        assert widget.study is wb.study and widget.on_navigate == wb.navigate
        assert wb._shell.panes[f"{STEP}{name}"] is widget.root
    wb._shell.show(f"{STEP}Column packing")
    warned = {key: text for key, text in warnings_of(wb).items() if text}
    assert list(warned) == [f"{STEP}Column packing"]
    assert "accept Extra-column volume first" in warned[f"{STEP}Column packing"]

    calls.clear()
    for target, context in [("measurements", {}), ("step", {"name": "Extra-column volume"}),
                            ("step", {"name": "Column packing"}), ("parameters", {}),
                            ("guide", {}), ("system", {}), ("setup", {})]:
        wb.navigate(target, context)
    assert calls == []


def test_navigate_shows_panes_and_highlights_units(example):
    example.navigate("step", {"name": "Column packing"})
    assert example._shell.current == f"{STEP}Column packing"
    assert set(example.instrument._diagram._highlight) == {"column"}

    example.instrument.set_hardware_expanded(False)
    example.navigate("system", {"unit": "tubing_pre_column"})
    assert example._shell.current == "System: Instrument"
    assert example.instrument.hardware_expanded
    assert set(example.instrument._diagram._highlight) == {"tubing_pre_column"}

    example.navigate("measurements", {"select": "System pulse 2 (UV)"})
    assert example.comparisons.selected.name == "System pulse 2 (UV)"
    example.navigate("measurements", {"experiment_type": "system_pulse"})
    assert example.comparisons._flow.experiment_type.id == "system_pulse"
    with pytest.raises(ValueError, match="Unknown navigation target"):
        example.navigate("nowhere")


def test_step_panes_follow_added_renamed_and_reloaded_steps(example, tmp_path):
    widget = example.add_step()
    assert widget.step_name == "step_3"
    assert example._shell.current == f"{STEP}step_3"
    assert "No measurements attached." in warnings_of(example)[f"{STEP}step_3"]
    with pytest.raises(ValueError, match="already exists"):
        example.add_step("step_3")

    widget.form.name.value = "renamed"
    assert f"{STEP}step_3" not in example._shell.panes
    assert example._shell.current == f"{STEP}renamed"
    assert example.steps["renamed"] is widget

    other = Study.load(MANIFEST)
    other.steps = other.steps[1:]
    example.parameters.load_study(other.save(tmp_path / "study.json"))
    assert list(example.steps) == ["Column packing"]


def test_sidebar_flags_measurement_step_and_chain_problems(example):
    study = example.study
    study.comparison("System pulse 1 (UV)").channel = "no such channel"
    study.steps[1].requires = ("flow_sheet.tubing_pre_column.length",)
    study.steps[0].requires = ("flow_sheet.column.bed_porosity",)
    study.notify()
    example._shell.show(f"{STEP}Extra-column volume")

    found = warnings_of(example)
    assert "System pulse 1 (UV): Unknown channel" in found["Measurements"]
    assert "System pulse 1 (UV)" in found[f"{STEP}Extra-column volume"]
    assert "accept Extra-column volume first" in found[f"{STEP}Column packing"]
    assert "Extra-column volume" in found["Parameters"]

    study.steps[0].requires = ()
    study.accept("Extra-column volume", study.initial_store.updated(
        {"flow_sheet.tubing_pre_column.length": 0.42}, Provenance(step="Extra-column volume"),
    ))
    found = warnings_of(example)
    assert "length (Tubing (pre column))" not in found[f"{STEP}Column packing"]
    assert found["Parameters"] == ""


def test_setup_buttons_navigate_set_up_steps_and_see_fitted_ones(example):
    example.setup.buttons["system_periphery"].click()
    assert example._shell.current == f"{STEP}Extra-column volume"
    example.navigate("setup")
    example.setup.buttons["system"].click()
    assert example._shell.current == "System: Instrument"
    example.navigate("setup")
    example.setup.buttons["particle_transport"].click()
    assert example._shell.current == "Measurements"

    large = example.study.comparison("Large tracer pulse 1 (UV)")
    example.study.upsert_comparison(dataclasses.replace(
        large, name="Protein pulse 1", experiment_type="nonbinding_protein_pulse"
    ))
    example.navigate("setup")
    example.setup.buttons["particle_transport"].click()
    assert example.study.steps[-1].name == "Particle transport"
    assert example._shell.current == f"{STEP}Particle transport"

    example.steps["Extra-column volume"].results.result = object()
    assert example.fitted_steps == {"Extra-column volume"}
    example.navigate("setup")
    assert example.setup.statuses["Extra-column volume"].fitted


def test_the_system_pane_supplies_the_recipe_of_new_measurements():
    wb = CharacterizationWorkbenchWidget()
    wb.instrument._sample_loop_checkbox.value = False
    wb.flow_rate.field.value = "0.5"
    assert wb.configuration.snapshot().model_values["flow_rate"] == pytest.approx(
        0.5 * ML_PER_MIN
    )
    assert warnings_of(wb)["System"] == ""

    wb._nav.index = nav_keys(wb).index("Measurements")
    flow = add_measurement(wb, "system_pulse_1_uv.csv", "linear_gradient_elution", "Protein")
    assert flow._flow_rate.value == "0.5"
    added = flow.confirm()

    assert added.recipe.instrument.include_sample_loop is True
    assert added.resolved_flow_rate == pytest.approx(0.5 * ML_PER_MIN)
    assert added.recipe.model_values["flow_rate_wash"] == pytest.approx(0.5 * ML_PER_MIN)
    wb._nav.index = nav_keys(wb).index("Setup")
    assert wb.setup.buttons["binding"].description.startswith("Set up this step")
    wb.flow_rate.field.value = "abc"
    assert wb.configuration.flow_rate == pytest.approx(0.5 * ML_PER_MIN)


def test_applying_the_configuration_keeps_the_measurements_own_method(example):
    name = "Large tracer pulse 1 (UV)"
    example.comparisons.select(name)
    before = example.study.comparison(name).recipe
    example.instrument._unit_checkboxes["tubing_post_column"].value = True
    example.configuration.column_form.element("length").value = 0.123

    example.comparisons._recipe_source.value = "__configuration__"
    example.comparisons._btn_use_recipe.click()

    after = example.study.comparison(name).recipe
    assert after.template_key == before.template_key
    assert after.model_values == before.model_values
    assert after.instrument.bypass_units == before.instrument.bypass_units
    assert after.column_values["length"] == 0.123
    assert example.study.comparison(name).problems() == []
    assert list(example.components.rows) == EXAMPLE
