from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import ipywidgets as W
import pytest
from cadetgui import configuration_store
from cadetgui.cadetprocessadapter import PARAMS
from cadetgui.experimental_data import read_experimental_csv
from cadetgui.study import Study
from cadetgui.widgets.composite import ComparisonsWidget, DataImportWidget

MANIFEST = (
    Path(__file__).parent.parent / "examples" / "data" / "characterization_akta" / "manifest.json"
)
FILM = "flow_sheet.column.film_diffusion"


@pytest.fixture
def study() -> Study:
    return Study.load(MANIFEST)


@pytest.fixture
def widget(study) -> ComparisonsWidget:
    return ComparisonsWidget(study)


def _row_text(widget, group, index):
    return [cell["text"] for cell in widget._tables[group].rows[index]]


def _pick_component(flow, name):
    if name in [value for _, value in flow._component._options]:
        flow._component.value = name
    elif name:
        flow.new_component(name)
    else:
        flow._component.value = None


def _walk_to_confirm(widget, file_name, channel, type_id, component):
    flow = widget._flow
    widget.start_add()
    flow.load_bytes(file_name, (MANIFEST.parent / file_name).read_bytes())
    flow.next()
    flow._channel.value = channel
    flow.next()
    flow._type_table.value = type_id
    flow.next()
    _pick_component(flow, component)
    flow.next()
    assert flow.page == 4
    return flow


def test_lists_measurements_grouped_by_the_step_they_feed(widget, study):
    assert widget._tables["system_periphery"].option_labels == [
        "System pulse 1 (UV)", "System pulse 2 (UV)",
    ]
    assert widget._tables["column_packing"].option_labels == [
        "Small tracer pulse 1 (conductivity)",
        "Small tracer pulse 2 (conductivity)",
        "Large tracer pulse 1 (UV)",
        "Large tracer pulse 2 (UV)",
    ]
    assert _row_text(widget, "system_periphery", 0) == [
        "System pulse 1 (UV)", "System pulse (no column in line)", "UV (UV 1_280)",
        "Extra-column volume", "ok",
    ]
    assert widget.selected is study.comparisons[0]
    assert widget._tables["system_periphery"].value == "System pulse 1 (UV)"
    assert widget._tables["column_packing"].value is None
    assert "No problems" in widget._problems_html.value
    headings = " ".join(c.value for c in widget._list_box.children if isinstance(c, W.HTML))
    assert "Binding" in headings and "Capacity" in headings

    widget._tables["column_packing"].value = "Large tracer pulse 1 (UV)"
    assert widget.selected.name == "Large tracer pulse 1 (UV)"
    assert widget._tables["system_periphery"].value is None


def test_untagged_measurements_are_not_assigned(widget, study):
    widget._experiment_type.value = None
    assert study.comparison("System pulse 1 (UV)").experiment_type is None
    assert widget._tables[None].option_labels == ["System pulse 1 (UV)"]
    assert widget._tables["system_periphery"].option_labels == ["System pulse 2 (UV)"]
    assert widget.selected.name == "System pulse 1 (UV)"


def test_recipe_card_is_plain_text_with_the_diagram(widget):
    widget.select("Small tracer pulse 1 (conductivity)")
    summary = widget._recipe_summary.value
    assert "{" not in summary and "}" not in summary
    assert "mL/min" in summary and "µL" in summary
    assert "Pulse Injection" in summary and "SmallTracer" in summary
    assert "Tubing (post column)" in summary
    assert "<svg" in widget._diagram.value
    assert 'data-observe' in widget._diagram.value


def test_editor_offers_pickers_from_the_run_and_the_recipe(widget):
    widget.select("Small tracer pulse 1 (conductivity)")
    assert widget._channel.option_labels == list(widget.selected.run.channels)
    assert "Phase Elution" in widget._marker.value
    assert "column.outlet" in [value for _, value in widget._solution_path._options]
    assert widget._baseline_start.units == widget.selected.run.x_unit
    assert "Cycle time" in " ".join(f.label for _, f in widget._override_fields.values())
    assert list(widget._component_fields) == widget.selected.recipe.components
    assert widget._advanced.selected_index is None


def test_edits_write_through_to_the_study_and_its_steps(widget, study):
    widget._metric.value = "SSE"
    widget._flow_rate.value = "0.5"
    widget._window_start.value = "10"

    edited = study.comparison("System pulse 1 (UV)")
    assert edited.metric == "SSE"
    assert edited.flow_rate == pytest.approx(0.5e-6 / 60)
    assert edited.window == (10.0, None)
    assert study.steps[0].comparisons[0] is edited
    assert "0.5 mL/min (this run)" in widget._recipe_summary.value

    widget._flow_rate.value = ""
    assert study.comparison("System pulse 1 (UV)").flow_rate is None


def test_rename_updates_steps_and_rejects_duplicates(widget, study):
    widget._name.value = "System A"
    assert study.steps[0].comparisons[0].name == "System A"
    assert widget.selected.name == "System A"
    assert widget._tables["system_periphery"].value == "System A"

    widget._name.value = "System pulse 2 (UV)"
    assert widget._name.error
    assert [c.name for c in study.comparisons].count("System pulse 2 (UV)") == 1
    assert "Fix Name" in widget._problems_html.value


def test_problems_show_in_the_list_and_the_card_with_advice(widget, study):
    widget._marker.value = None
    widget._injection_x.value = "0.5"
    assert study.comparison("System pulse 1 (UV)").measured_injection == 0.5
    assert study.comparison("System pulse 1 (UV)").injection_marker is None

    widget._normalization.value = "area"
    widget._target_area.value = ""
    assert "target_area" in widget._problems_html.value
    assert "What to do" in widget._problems_html.value
    assert _row_text(widget, "system_periphery", 0)[4] == "1 problem"
    assert widget._tables["system_periphery"].rows[0][4]["chip"] == "error"


def test_overrides_and_components(widget, study):
    widget.select("Small tracer pulse 1 (conductivity)")
    _, cycle_time = widget._override_fields["cycle_time"]
    cycle_time.value = "300"
    widget._component_fields["SmallTracer"].value = False
    comparison = study.comparison("Small tracer pulse 1 (conductivity)")
    assert comparison.overrides == {"cycle_time": 300.0}
    assert comparison.components is None


def test_step_add_opens_the_stepper_duplicate_and_remove(widget, study):
    n = len(study.comparisons)
    assert not widget._flow.is_open
    widget._group_button("system_periphery").click()
    assert widget._flow.is_open and widget._flow.page == 0

    widget._on_duplicate(None)
    assert widget.selected.name == "System pulse 1 (UV) copy"
    assert widget.selected.recipe is not study.comparison("System pulse 1 (UV)").recipe
    assert "System pulse 1 (UV) copy" in widget._tables["system_periphery"].option_labels

    widget._on_remove(None)
    assert len(study.comparisons) == n

    widget.select("System pulse 1 (UV)")
    widget._on_remove(None)
    assert "Extra-column volume" in widget._remove_note.value
    assert "System pulse 1 (UV)" in [c.name for c in study.comparisons]
    widget._btn_remove_cancel.click()
    assert widget._remove_confirm.layout.display == "none"
    assert "System pulse 1 (UV)" in [c.name for c in study.comparisons]


def test_recipe_from_configuration_and_store(study, tmp_path):
    recipe = study.comparison("Small tracer pulse 1 (conductivity)").recipe
    applied = []
    configuration = SimpleNamespace(
        snapshot=lambda: recipe,
        show_process_template=True,
        _apply_state=lambda name, state: applied.append((name, state)),
        persistence=SimpleNamespace(store_dir=tmp_path),
    )
    configuration_store.save_to_store(recipe, "column recipe", store_dir=tmp_path)
    widget = ComparisonsWidget(study, configuration=configuration)
    labels = widget._recipe_source.option_labels
    assert labels[1] == "Current configuration" and labels[2].startswith("Saved: column recipe")

    widget._recipe_source.selected_index = 1
    widget._on_use_recipe(None)
    assert study.comparison("System pulse 1 (UV)").recipe is recipe
    assert "Column" in widget._recipe_summary.value

    widget._recipe_source.selected_index = 2
    widget._on_use_recipe(None)
    assert study.comparison("System pulse 1 (UV)").recipe == recipe


def test_runs_from_the_data_import_widget_are_offered(study):
    data = DataImportWidget()
    run = read_experimental_csv(
        (MANIFEST.parent / "system_pulse_2_uv.csv").read_bytes(), "imported",
    )
    data._add_dataset_from_channel(run, next(iter(run.channels)), 1e-8)
    data._finish_import()
    widget = ComparisonsWidget(study, data=data)
    assert "imported.csv" in [value for _, value in widget._run._options]

    widget._run.value = "imported.csv"
    edited = study.comparison("System pulse 1 (UV)")
    assert edited.run is run and edited.data_file == "imported.csv"


def test_add_measurement_from_akta_bytes(widget, study):
    flow = widget._flow
    widget.start_add()
    flow.next()
    assert flow.page == 0 and "Upload" in flow.status.value

    flow.load_bytes(
        "large_tracer_pulse_1_uv.csv",
        (MANIFEST.parent / "large_tracer_pulse_1_uv.csv").read_bytes(),
    )
    assert "ÄKTA" in flow._run_note.value
    flow.next()
    assert flow._channel.option_labels == ["UV 1_280", "Cond"]
    assert flow._channel_chart.series[0]["name"] == "UV 1_280"
    assert flow._channel_chart.x_unit == "mL"
    assert "Phase Elution" in flow._markers.value

    flow.next()
    assert flow._type_table.value is None
    detectors = [row[2] for row in flow._type_table.rows]
    assert {"text": "UV · matches channel", "chip": "ok"} in detectors
    flow.next()
    assert flow.page == 2
    flow._type_table.value = "column_pulse_large_tracer"
    assert "excluded from the" in flow._type_help.value

    flow.next()
    assert flow._name.value == "large_tracer_pulse_1_uv"
    assert flow._component.value == "LargeTracer"
    assert flow._component.option_labels == [
        "LargeTracer (large tracer)",
        "SystemTracer (system tracer — not a large tracer)",
        "SmallTracer (small tracer — not a large tracer)",
        "New component…",
    ]
    assert flow._flow_rate.value == "0.498"
    assert flow._marker.value == "Phase Elution"
    flow.new_component("Dextran")

    flow.next()
    assert "recipe of measurement 'System pulse 1 (UV)'" in flow._base_note.value
    assert "{" not in flow._summary.value and "<svg" in flow._diagram.value
    assert "No problems" in flow._confirm_problems.value
    assert flow._implied.layout.display == ""

    comparison = flow.confirm()
    added = study.comparison("large_tracer_pulse_1_uv")
    assert added is comparison
    assert added.experiment_type == "column_pulse_large_tracer"
    assert added.probe == "Dextran" and added.data_file == "large_tracer_pulse_1_uv.csv"
    assert added.solution_path == "column.outlet"
    assert added.flow_rate is None
    assert added.problems() == []
    assert "Dextran" not in study.initial_store.entries[FILM].value
    assert not flow.is_open
    assert widget.selected is added
    assert "large_tracer_pulse_1_uv" in widget._tables["column_packing"].option_labels
    assert "Column packing" in widget.status.value
    assert "large_tracer_pulse_1_uv.csv" in [value for _, value in widget._run._options]


def test_implied_values_only_when_ticked(widget, study):
    calls = []
    study.add_listener(lambda: calls.append(1))
    flow = _walk_to_confirm(
        widget, "large_tracer_pulse_2_uv.csv", "UV 1_280", "column_pulse_large_tracer", "Dex"
    )
    flow._implied.value = True
    flow.confirm()
    entry = study.initial_store.entries[FILM]
    assert entry.value["Dex"] == 0.0
    assert entry.value["SmallTracer"] == 8e-05
    assert "film_diffusion" in widget.status.value
    assert len(calls) >= 2


def test_types_without_implied_values_hide_the_option(widget):
    flow = _walk_to_confirm(widget, "system_pulse_1_uv.csv", "UV 1_280", "system_pulse", "Acetone")
    assert flow._implied.layout.display == "none"


def test_step_button_preselects_the_step_type(widget):
    widget._group_button("binding").click()
    assert widget._flow.is_open
    assert widget._flow._type_table.value == "linear_gradient_elution"


def test_other_type_adds_an_unassigned_measurement(widget, study):
    flow = _walk_to_confirm(widget, "system_pulse_1_uv.csv", "Cond", "__other__", "")
    flow.confirm()
    added = study.comparison(flow._name.value)
    assert added.experiment_type is None and added.channel == "Cond"
    assert added.recipe == study.comparison("System pulse 1 (UV)").recipe
    assert widget._tables[None].option_labels == [added.name]


def test_generic_csv_asks_for_column_roles(widget, tmp_path):
    flow = widget._flow
    widget.start_add()
    content = b"Time (min),UV,Cond\n0,1,2\n1,3,4\n2,5,6\n"
    flow.load_bytes("run.csv", content)
    assert flow.run is None
    roles = [d.value for d in flow._role_dropdowns]
    assert roles == ["time_min", "signal", "signal"]
    flow._apply_roles()
    assert list(flow.run.channels) == ["UV", "Cond"] and flow.data_file == "run.csv"

    flow.load_bytes("two.csv", b"Time,Signal\n0,1\n1,2\n")
    assert flow.run.x_basis == "time" and flow.run.channels["Signal"].x[1] == 60.0


def test_no_base_recipe_blocks_confirm():
    widget = ComparisonsWidget(Study())
    flow = widget._flow
    widget.start_add()
    flow.load_bytes(
        "system_pulse_1_uv.csv", (MANIFEST.parent / "system_pulse_1_uv.csv").read_bytes(),
    )
    flow.next()
    flow.next()
    flow._type_table.value = "system_pulse"
    flow.next()
    flow.new_component("Acetone")
    flow.next()
    assert "Process Configuration" in flow._confirm_problems.value
    assert flow._btn_add.disabled
    assert flow.confirm() is None
    assert widget.study.comparisons == []


def test_measured_trace_is_shown_as_the_fit_sees_it_without_simulating(widget, study):
    widget.select("System pulse 1 (UV)")
    (series,) = widget._measured_chart.series
    assert series["name"] == "System pulse 1 (UV)" and series["reference"]
    assert len(series["times"]) == len(series["values"]) > 10
    assert widget._measured_note.value == ""


def test_a_trace_that_cannot_be_prepared_is_shown_raw_with_the_reason(widget, study):
    comparison = study.comparison("Small tracer pulse 1 (conductivity)")
    study.replace_comparison(comparison.name, dataclasses.replace(comparison, baseline_window=None))
    widget.select(comparison.name)
    assert widget._measured_chart.series
    assert "raw trace" in widget._measured_note.value
    assert "No flat baseline found" in widget._problems_html.value
    assert "Set a baseline window" in widget._problems_html.value


def test_add_flow_opens_under_its_step_heading_and_follows_the_type(widget):
    from cadetgui.characterization_guide import CHAIN_BY_ID

    def position(step_id):
        children = list(widget._list_box.children)
        title = CHAIN_BY_ID[step_id].title
        heading = next(
            i for i, c in enumerate(children)
            if isinstance(c, type(children[0])) and hasattr(c, "value")
            and title in getattr(c, "value", "")
        )
        return heading, children.index(widget._flow.root)

    widget._group_button("column_packing").click()
    heading, flow = position("column_packing")
    assert flow == heading + 1
    assert widget._group_button("column_packing") not in widget._list_box.children
    assert CHAIN_BY_ID["column_packing"].title in widget._flow._title.value

    widget._flow._type_table.value = "system_pulse"
    heading, flow = position("system_periphery")
    assert flow == heading + 1
    assert CHAIN_BY_ID["system_periphery"].title in widget._flow._title.value

    widget._flow.close()
    assert widget._flow.root not in widget._list_box.children
    assert widget._group_button("column_packing") in widget._list_box.children


def test_other_type_offers_a_process_template_that_sets_the_new_recipe(widget, study):
    from cadetgui.cadetprocessadapter import INSTRUMENT_TEMPLATES

    flow = widget._flow
    widget.start_add()
    flow.load_bytes(
        "system_pulse_1_uv.csv", (MANIFEST.parent / "system_pulse_1_uv.csv").read_bytes()
    )
    flow.next()
    flow.next()
    flow._type_table.value = "system_pulse"
    assert flow._other_template_box.layout.display == "none"
    flow._type_table.value = "__other__"
    assert flow._other_template_box.layout.display == ""
    assert flow._other_template.option_labels == list(INSTRUMENT_TEMPLATES)
    base = study.comparison("System pulse 1 (UV)").recipe
    assert flow._other_template.value == base.template_key

    flow._other_template.value = "Step"
    flow.next()
    flow.next()
    assert "Step" in flow._summary.value
    added = flow.confirm()

    assert added.recipe.template_key == "Step"
    assert set(added.recipe.model_values) == {"c_buffer_a", "c_buffer_b", "cycle_time", "flow_rate"}
    assert added.recipe.model_values["flow_rate"] == base.model_values["flow_rate"]
    assert added.recipe.instrument == base.instrument


def test_recipe_with_template_uses_defaults_keeps_flow_rate_and_adds_the_loop(study):
    import dataclasses

    from cadetgui.widgets.composite._measurement_common import recipe_with_template

    base = study.comparison("System pulse 1 (UV)").recipe
    no_loop = dataclasses.replace(
        base, instrument=dataclasses.replace(base.instrument, include_sample_loop=False)
    )
    lwe = recipe_with_template(no_loop, "Load–Wash–Elute (LWE)")

    assert lwe.template_key == "Load–Wash–Elute (LWE)"
    assert lwe.model_values["flow_rate_wash"] == base.model_values["flow_rate"]
    assert lwe.model_values["delta_t_wash"] == PARAMS["delta_t_wash"].default
    assert lwe.instrument.include_sample_loop is True
    assert lwe.column_values == base.column_values


def test_editor_changes_the_process_template_with_a_method_warning(widget, study):
    name = "System pulse 1 (UV)"
    widget.select(name)
    before = study.comparison(name).recipe
    assert widget._template.value == "Pulse Injection"
    assert "changes this measurement's method" in widget._template_note.value

    widget._template.value = "Breakthrough"

    edited = study.comparison(name)
    assert edited.recipe.template_key == "Breakthrough"
    assert "sample_buffer" in edited.recipe.model_values
    assert edited.recipe.model_values["flow_rate"] == before.model_values["flow_rate"]
    assert "Breakthrough" in widget._recipe_summary.value


def _upload(flow, file_name):
    flow.load_bytes(file_name, (MANIFEST.parent / file_name).read_bytes())


def test_flow_from_a_one_type_step_skips_the_type_page(widget, study):
    flow = widget._flow
    widget._group_button("system_periphery").click()
    assert flow.pages == ["Upload", "Channel", "Details", "Confirm"]
    assert "Experiment type" not in flow._progress.value
    assert "4 Confirm" in flow._progress.value
    _upload(flow, "system_pulse_1_uv.csv")
    flow.next()
    flow.next()
    assert flow.page == 3
    assert flow._step_type.layout.display == "none"
    info = flow._step_type_info.value
    assert "System pulse (no column in line)" in info and "what you run" in info
    assert flow.experiment_type.id == "system_pulse"
    assert "Extra-column volume" in flow._title.value
    flow.back()
    assert flow.page == 1
    flow.next()
    flow.next()
    assert flow.page == 4
    added = flow.confirm()
    assert added.experiment_type == "system_pulse"


@pytest.mark.parametrize("channel, expected", [
    ("Cond", "column_pulse_small_tracer"),
    ("UV 1_280", "column_pulse_large_tracer"),
])
def test_flow_from_column_packing_offers_its_types_by_detector(widget, channel, expected):
    flow = widget._flow
    widget.start_add(step_id="column_packing")
    assert "Experiment type" not in flow.pages
    _upload(flow, "large_tracer_pulse_1_uv.csv")
    flow.next()
    flow._channel.value = channel
    flow.next()
    assert flow._step_type.layout.display == ""
    assert [v for _, v in flow._step_type.options] == [
        "column_pulse_small_tracer", "column_pulse_large_tracer",
    ]
    assert flow._step_type.value == expected
    assert flow.experiment_type.id == expected
    assert "excluded from the pores" in flow._step_type_info.value


def test_flow_step_type_choice_updates_the_details(widget):
    flow = widget._flow
    widget.start_add(step_id="column_packing")
    assert "Experiment type" not in flow.pages
    _upload(flow, "large_tracer_pulse_1_uv.csv")
    flow.next()
    flow.next()
    assert flow._step_type.value == "column_pulse_large_tracer"
    assert flow._component.value == "LargeTracer"
    flow._step_type.value = "column_pulse_small_tracer"
    assert flow.experiment_type.id == "column_pulse_small_tracer"
    assert flow._component.value == "SmallTracer"
    flow.back()
    flow._channel.value = "Cond"
    flow.next()
    assert flow._step_type.value == "column_pulse_small_tracer"


def test_an_explicit_experiment_type_is_not_overridden_by_the_detector(widget):
    flow = widget._flow
    widget.start_add(experiment_type="column_pulse_small_tracer")
    _upload(flow, "large_tracer_pulse_1_uv.csv")
    flow.next()
    flow.next()
    assert flow._step_type.value == "column_pulse_small_tracer"


def test_programmatic_start_keeps_the_type_page(widget):
    flow = widget._flow
    widget.start_add()
    assert flow.pages == ["Upload", "Channel", "Experiment type", "Details", "Confirm"]
    assert flow._step_type_box.layout.display == "none"
    assert "3 Experiment type" in flow._progress.value
    assert "Other: set up everything by hand" in flow._type_table.option_labels


def _walk_to_details(widget, file_name, channel, type_id):
    flow = widget._flow
    widget.start_add()
    flow.load_bytes(file_name, (MANIFEST.parent / file_name).read_bytes())
    flow.next()
    flow._channel.value = channel
    flow.next()
    flow._type_table.value = type_id
    flow.next()
    assert flow.page == 3
    return flow


def test_a_component_with_another_role_is_listed_and_can_take_the_needed_role(widget, study):
    flow = _walk_to_details(
        widget, "small_tracer_pulse_1_conductivity.csv", "Cond", "column_pulse_small_tracer"
    )
    labels = flow._component.option_labels
    other = "SystemTracer (system tracer — not a small tracer)"
    assert labels.index("SmallTracer (small tracer)") < labels.index(other)

    flow.new_component("SystemTracer")
    assert "pick it from the list" not in flow._new_component.error
    assert "already declared as system tracer" in flow._new_component.error

    flow._component.value = "SystemTracer"
    assert (
        "SystemTracer is declared as a system tracer. This experiment needs a small tracer."
        in flow._role_fix.value
    )
    assert flow._btn_role_fix.description == "Make SystemTracer a small tracer"
    flow.next()
    assert flow.page == 3 and "Change its role" in flow.status.value
    assert study.component("SystemTracer").role == "system tracer"

    flow._btn_role_fix.click()
    assert study.component("SystemTracer").role == "small tracer"
    assert flow._component.value == "SystemTracer"
    assert flow._role_fix.value == "" and flow._btn_role_fix.layout.display == "none"
    assert study.measurement_problems(study.comparison("System pulse 1 (UV)")) == []


def test_a_role_change_that_would_break_other_measurements_is_explained(widget, study):
    flow = _walk_to_details(
        widget, "large_tracer_pulse_1_uv.csv", "UV 1_280", "column_pulse_large_tracer"
    )
    flow._component.value = "SystemTracer"

    text = flow._role_fix.value
    assert "This experiment needs a large tracer" in text
    assert "System pulse 1 (UV) (System pulse" in text and "need that role" in text
    assert "name a new one" in text
    assert flow._btn_role_fix.layout.display == "none"
    flow.make_component_fit()
    assert study.component("SystemTracer").role == "system tracer"


def test_the_advanced_component_picker_offers_the_role_change(widget, study):
    widget.select("Small tracer pulse 1 (conductivity)")
    study.add_component("Acetone", "system tracer")
    assert "Acetone (system tracer — not a small tracer)" in widget._probe.option_labels

    widget._probe.value = "Acetone"
    assert "Acetone is declared as a system tracer" in widget._probe_role_fix.value
    assert widget._btn_probe_role_fix.description == "Make Acetone a small tracer"

    widget._btn_probe_role_fix.click()
    assert study.component("Acetone").role == "small tracer"
    assert widget._btn_probe_role_fix.layout.display == "none"
    assert study.component_problems(study.comparison("Small tracer pulse 1 (conductivity)")) == []


def test_advanced_is_split_into_titled_sections_with_every_control(widget):
    widget.select("Small tracer pulse 1 (conductivity)")
    assert widget._advanced.titles[0].startswith(
        "Advanced: fine-tune how this measurement is compared"
    )
    assert "defaults from its experiment type are usually right" in widget._advanced.titles[0]
    assert list(widget._advanced_sections) == [
        "Data and alignment", "Baseline and scaling", "Simulated signal", "Comparison",
        "Process", "Name and type",
    ]
    expected = {
        "Data and alignment": [
            widget._run, widget._channel, widget._marker, widget._injection_x,
            widget._flow_rate,
        ],
        "Baseline and scaling": [
            widget._baseline_start, widget._baseline_end, widget._normalization,
            widget._target_area,
        ],
        "Simulated signal": [widget._solution_path, widget._components_box, widget._probe],
        "Comparison": [widget._metric, widget._window_start, widget._window_end],
        "Process": [
            widget._template, widget._overrides_box, widget._recipe_source,
            widget._btn_use_recipe,
        ],
        "Name and type": [widget._name, widget._experiment_type],
    }
    for title, controls in expected.items():
        section = widget._advanced_sections[title]
        inside = list(_walk(section))
        assert title in section.children[0].value
        assert "Change" in section.children[1].value
        for control in controls:
            assert any(w is control for w in inside), (title, control)
        assert any(w is section for w in _walk(widget._advanced))
    card = list(_walk(widget._card))
    assert any(w is widget._measured_chart for w in card)


def _walk(widget):
    yield widget
    for child in getattr(widget, "children", ()):
        yield from _walk(child)


def _rendered(widget) -> str:
    parts = []
    for w in _walk(widget):
        if isinstance(w, W.HTML) and "<style" not in w.value:
            parts.append(w.value)
        for attr in ("description", "label"):
            if isinstance(getattr(w, attr, None), str):
                parts.append(getattr(w, attr))
        parts += list(getattr(w, "option_labels", ()))
        parts += [str(t) for t in getattr(w, "titles", ()) or ()]
    return " ".join(parts)


def test_measurement_pane_avoids_stage_wording(widget):
    widget.select("System pulse 1 (UV)")
    text = _rendered(widget.root).lower()
    assert "stage" not in text and "fit step" not in text
    assert "check alignment and baseline here" in text
