"""The Measurements pane: list, edit, remove and the add-measurement stepper."""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest
from cadetgui.characterization.study import Study, StudyComponent
from cadetgui.instrument.recipes import recipe_with_template
from cadetgui.instrument.templates import INSTRUMENT_TEMPLATES, PARAMS
from cadetgui.io import configuration_store
from cadetgui.widgets.characterization import ComparisonsWidget

from characterization.synthetic import FILM, data_bytes

LARGE = "large_tracer_pulse_1_uv.csv"


@pytest.fixture
def widget(study) -> ComparisonsWidget:
    return ComparisonsWidget(study)


def to_details(widget, file_name, type_id, channel=None):
    """Open the stepper, upload `file_name` and walk to the Details page of `type_id`."""
    flow = widget._flow
    widget.start_add()
    flow.load_bytes(file_name, data_bytes(file_name))
    flow.next()
    if channel is not None:
        flow._channel.value = channel
    flow.next()
    flow._type_table.value = type_id
    flow.next()
    assert flow.page == 3
    return flow


def to_confirm(widget, file_name, type_id, component, channel=None):
    flow = to_details(widget, file_name, type_id, channel)
    if component in [value for _, value in flow._component._options]:
        flow._component.value = component
    elif component:
        flow.new_component(component)
    flow.next()
    assert flow.page == 4
    return flow


def test_lists_measurements_by_the_step_they_feed_and_selects_one(widget, study):
    assert widget._tables["system_periphery"].option_labels == [
        "System pulse 1 (UV)", "System pulse 2 (UV)",
    ]
    assert len(widget._tables["column_packing"].option_labels) == 4
    assert widget.selected is study.comparisons[0]

    widget._tables["column_packing"].value = "Large tracer pulse 1 (UV)"
    assert widget.selected.name == "Large tracer pulse 1 (UV)"
    assert widget._tables["system_periphery"].value is None

    widget._experiment_type.value = None
    widget.select("System pulse 2 (UV)")
    assert widget._tables[None].option_labels == ["Large tracer pulse 1 (UV)"]


def test_edits_write_through_to_the_study_and_its_steps(widget, study):
    notified = []
    widget.add_listener(lambda: notified.append(1))
    widget._metric.value = "SSE"
    widget._flow_rate.value = "0.5"
    widget._window_start.value = "10"

    edited = study.comparison("System pulse 1 (UV)")
    assert (edited.metric, edited.window) == ("SSE", (10.0, None))
    assert edited.flow_rate == pytest.approx(0.5e-6 / 60)
    assert study.steps[0].comparisons[0] is edited
    assert len(notified) == 3
    widget._flow_rate.value = ""
    assert study.comparison("System pulse 1 (UV)").flow_rate is None

    widget._name.value = "System A"
    assert study.steps[0].comparisons[0].name == "System A"
    assert widget._tables["system_periphery"].value == "System A"
    widget._name.value = "System pulse 2 (UV)"
    assert widget._name.error
    assert [c.name for c in study.comparisons].count("System pulse 2 (UV)") == 1


def test_overrides_components_and_template_edits(widget, study):
    name = "Small tracer pulse 1 (conductivity)"
    widget.select(name)
    before = study.comparison(name).recipe
    widget._override_fields["cycle_time"][1].value = "300"
    widget._component_fields["SmallTracer"].value = False
    assert study.comparison(name).overrides == {"cycle_time": 300.0}
    assert study.comparison(name).components is None

    widget._template.value = "Breakthrough"

    edited = study.comparison(name).recipe
    assert edited.template_key == "Breakthrough" and "sample_buffer" in edited.model_values
    assert edited.model_values["flow_rate"] == before.model_values["flow_rate"]


def test_problems_show_in_the_list_and_the_card(widget, study):
    widget._marker.value = None
    widget._injection_x.value = "0.5"
    assert study.comparison("System pulse 1 (UV)").measured_injection == 0.5
    widget._normalization.value = "area"
    widget._target_area.value = ""
    assert "target_area" in widget._problems_html.value
    assert widget._tables["system_periphery"].rows[0][4]["chip"] == "error"

    comparison = study.comparison("Small tracer pulse 1 (conductivity)")
    study.replace_comparison(comparison.name, dataclasses.replace(comparison, baseline_window=None))
    widget.select(comparison.name)
    assert widget._measured_chart.series
    assert "raw trace" in widget._measured_note.value
    assert "No flat baseline found" in widget._problems_html.value


def test_duplicate_and_remove_with_confirmation(widget, study):
    n = len(study.comparisons)
    widget._btn_duplicate.click()
    assert widget.selected.name == "System pulse 1 (UV) copy"
    assert widget.selected.recipe is not study.comparison("System pulse 1 (UV)").recipe
    widget._btn_remove.click()
    assert len(study.comparisons) == n

    widget.select("System pulse 1 (UV)")
    widget._btn_remove.click()
    assert "Extra-column volume" in widget._remove_note.value
    widget._btn_remove_cancel.click()
    assert "System pulse 1 (UV)" in [c.name for c in study.comparisons]
    widget._btn_remove.click()
    widget._btn_remove_confirm.click()
    assert "System pulse 1 (UV)" not in [c.name for c in study.comparisons]
    assert [c.name for c in study.steps[0].comparisons] == ["System pulse 2 (UV)"]


def test_recipe_from_the_configuration_or_the_store(study, tmp_path):
    recipe = study.comparison("Small tracer pulse 1 (conductivity)").recipe
    configuration = SimpleNamespace(
        snapshot=lambda: recipe, show_process_template=True,
        _apply_state=lambda name, state: None,
        persistence=SimpleNamespace(store_dir=tmp_path),
    )
    configuration_store.save_to_store(recipe, "column recipe", store_dir=tmp_path)
    widget = ComparisonsWidget(study, configuration=configuration)
    labels = widget._recipe_source.option_labels
    assert labels[1] == "Current configuration" and labels[2].startswith("Saved: column recipe")

    widget._recipe_source.selected_index = 1
    widget._btn_use_recipe.click()
    assert study.comparison("System pulse 1 (UV)").recipe is recipe
    widget._recipe_source.selected_index = 2
    widget._btn_use_recipe.click()
    assert study.comparison("System pulse 1 (UV)").recipe == recipe


def test_add_a_measurement_from_an_akta_export(widget, study):
    flow = widget._flow
    widget.start_add()
    flow.next()
    assert flow.page == 0 and "Upload" in flow.status.value
    flow.load_bytes(LARGE, data_bytes(LARGE))
    flow.next()
    assert flow._channel.option_labels == ["UV 1_280", "Cond"]
    flow.next()
    flow.next()
    assert flow.page == 2
    flow._type_table.value = "column_pulse_large_tracer"
    flow.next()
    assert flow._name.value == "large_tracer_pulse_1_uv"
    assert flow._component.value == "LargeTracer"
    assert flow._marker.value == "Phase Elution"
    flow.new_component("Dextran")
    flow.next()
    assert "No problems" in flow._confirm_problems.value

    added = flow.confirm()

    assert study.comparison("large_tracer_pulse_1_uv") is added
    assert added.experiment_type == "column_pulse_large_tracer"
    assert added.probe == "Dextran" and added.data_file == LARGE
    assert added.solution_path == "column.outlet" and added.problems() == []
    assert study.component("Dextran") == StudyComponent("Dextran", "large tracer")
    assert "Dextran" not in study.initial_store.entries[FILM].value
    assert not flow.is_open and widget.selected is added
    assert "large_tracer_pulse_1_uv" in widget._tables["column_packing"].option_labels


@pytest.mark.parametrize("type_id, implied", [
    ("column_pulse_large_tracer", True), ("system_pulse", False),
])
def test_implied_values_are_stored_only_when_ticked(widget, study, type_id, implied):
    flow = to_confirm(widget, "large_tracer_pulse_2_uv.csv", type_id, "Dex", "UV 1_280")
    assert (flow._implied.layout.display == "") == implied
    flow._implied.value = True
    flow.confirm()
    assert ("Dex" in study.initial_store.entries[FILM].value) == implied


def test_other_type_adds_an_unassigned_measurement_with_the_chosen_template(widget, study):
    flow = to_details(widget, "system_pulse_1_uv.csv", "__other__", "Cond")
    assert flow._other_template.option_labels == list(INSTRUMENT_TEMPLATES)
    flow._other_template.value = "Step"
    flow.next()
    added = flow.confirm()

    base = study.comparison("System pulse 1 (UV)").recipe
    assert added.experiment_type is None and added.channel == "Cond"
    assert added.recipe.template_key == "Step"
    assert added.recipe.model_values["flow_rate"] == base.model_values["flow_rate"]
    assert added.recipe.instrument == base.instrument
    assert widget._tables[None].option_labels == [added.name]


def test_recipe_with_template_keeps_flow_rate_and_adds_the_loop(study):
    base = study.comparison("System pulse 1 (UV)").recipe
    no_loop = dataclasses.replace(
        base, instrument=dataclasses.replace(base.instrument, include_sample_loop=False)
    )
    lwe = recipe_with_template(no_loop, "Load–Wash–Elute (LWE)")
    assert lwe.model_values["flow_rate_wash"] == base.model_values["flow_rate"]
    assert lwe.model_values["delta_t_wash"] == PARAMS["delta_t_wash"].default
    assert lwe.instrument.include_sample_loop is True
    assert lwe.column_values == base.column_values


def test_a_generic_csv_asks_for_column_roles(widget):
    flow = widget._flow
    widget.start_add()
    flow.load_bytes("run.csv", b"Time (min),UV,Cond\n0,1,2\n1,3,4\n2,5,6\n")
    assert flow.run is None
    assert [d.value for d in flow._role_dropdowns] == ["time_min", "signal", "signal"]
    flow._apply_roles()
    assert list(flow.run.channels) == ["UV", "Cond"] and flow.data_file == "run.csv"
    flow.load_bytes("two.csv", b"Time,Signal\n0,1\n1,2\n")
    assert flow.run.x_basis == "time" and flow.run.channels["Signal"].x[1] == 60.0


def test_without_a_base_recipe_nothing_is_added():
    widget = ComparisonsWidget(Study())
    flow = to_confirm(widget, "system_pulse_1_uv.csv", "system_pulse", "Acetone")
    assert "Process Configuration" in flow._confirm_problems.value
    assert flow._btn_add.disabled
    assert flow.confirm() is None and widget.study.comparisons == []


@pytest.mark.parametrize("start, pages, type_id", [
    ({"step_id": "system_periphery"}, 4, "system_pulse"),
    ({"step_id": "binding"}, 4, "linear_gradient_elution"),
    ({"step_id": "column_packing"}, 4, "column_pulse_large_tracer"),
    ({"experiment_type": "column_pulse_small_tracer"}, 4, "column_pulse_small_tracer"),
    ({}, 5, None),
])
def test_starting_from_a_step_or_type_preselects_the_experiment_type(
    widget, start, pages, type_id
):
    flow = widget._flow
    widget.start_add(**start)
    assert len(flow.pages) == pages
    flow.load_bytes(LARGE, data_bytes(LARGE))
    flow.next()
    flow.next()
    if pages == 4:
        assert flow.page == 3
    assert (flow.experiment_type.id if flow.experiment_type else None) == type_id


@pytest.mark.parametrize("channel, expected, component", [
    ("Cond", "column_pulse_small_tracer", "SmallTracer"),
    ("UV 1_280", "column_pulse_large_tracer", "LargeTracer"),
])
def test_a_two_type_step_picks_the_type_by_detector(widget, channel, expected, component):
    flow = widget._flow
    widget.start_add(step_id="column_packing")
    flow.load_bytes(LARGE, data_bytes(LARGE))
    flow.next()
    flow._channel.value = channel
    flow.next()
    assert [v for _, v in flow._step_type.options] == [
        "column_pulse_small_tracer", "column_pulse_large_tracer",
    ]
    assert flow._step_type.value == expected and flow._component.value == component
    other = next(v for _, v in flow._step_type.options if v != expected)
    flow._step_type.value = other
    assert flow.experiment_type.id == other


def test_the_component_picker_offers_fitting_components_first(widget, study):
    flow = to_details(widget, "system_pulse_1_uv.csv", "system_pulse")
    assert flow._component.option_labels == [
        "SystemTracer (system tracer)", "SmallTracer (small tracer)",
        "LargeTracer (large tracer — not a small tracer or system tracer)", "New component…",
    ]
    flow = to_details(widget, LARGE, "nonbinding_protein_pulse")
    assert flow._component.value == "__new__" and flow._new_role.value == "protein"
    flow.next()
    assert flow.page == 3 and "New component" in flow.status.value
    flow.new_component("SmallTracer")
    assert "already declared as small tracer" in flow._new_component.error
    flow.new_component("IgG")
    flow.next()
    assert flow.confirm().probe == "IgG"
    assert study.component("IgG") == StudyComponent("IgG", "protein")
    assert to_details(widget, "large_tracer_pulse_2_uv.csv",
                      "nonbinding_protein_pulse")._component.value == "IgG"


def test_a_component_with_another_role_can_take_the_needed_role(widget, study):
    flow = to_details(widget, "small_tracer_pulse_1_conductivity.csv",
                      "column_pulse_small_tracer", "Cond")
    flow._component.value = "SystemTracer"
    assert "This experiment needs a small tracer." in flow._role_fix.value
    flow.next()
    assert flow.page == 3 and "Change its role" in flow.status.value

    flow._btn_role_fix.click()

    assert study.component("SystemTracer").role == "small tracer"
    assert flow._role_fix.value == ""
    assert study.measurement_problems(study.comparison("System pulse 1 (UV)")) == []


def test_a_role_change_that_would_break_other_measurements_is_refused(widget, study):
    flow = to_details(widget, LARGE, "column_pulse_large_tracer", "UV 1_280")
    flow._component.value = "SystemTracer"
    assert "need that role" in flow._role_fix.value
    assert flow._btn_role_fix.layout.display == "none"
    flow.make_component_fit()
    assert study.component("SystemTracer").role == "system tracer"


def test_the_advanced_component_picker_follows_components_and_fixes_roles(widget, study):
    name = "Small tracer pulse 1 (conductivity)"
    widget.select(name)
    study.add_component("Acetone", "system tracer")
    assert "Acetone (system tracer — not a small tracer)" in widget._probe.option_labels

    widget._probe.value = "Acetone"
    edited = study.comparison(name)
    assert edited.probe == "Acetone" and edited.recipe.components == ["Acetone"]
    assert "declared as a system tracer" in widget._problems_html.value

    widget._btn_probe_role_fix.click()
    assert study.component("Acetone").role == "small tracer"
    assert study.component_problems(study.comparison(name)) == []
