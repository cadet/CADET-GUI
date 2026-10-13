"""ConfigurationWidget: models and templates it builds, validation, wiring to the instrument."""
from __future__ import annotations

import itertools

import numpy as np
import pytest
from cadetgui.characterization.guide import EXPERIMENT_TYPES
from cadetgui.instrument.system import (
    BINDING_MODELS,
    COLUMN_MODELS,
    INSTRUMENT_COMPATIBLE_COLUMNS,
)
from cadetgui.instrument.templates import INSTRUMENT_TEMPLATES, PARAMS
from cadetgui.widgets.instrument import ConfigurationWidget, InstrumentWidget
from CADETProcess.simulator import Cadet

SMA = "Steric Mass Action (SMA)"
LWE = "Load–Wash–Elute (LWE)"
LOOP_TEMPLATES = ("Pulse Injection", LWE, "Step Elution")
COLUMNS = sorted(INSTRUMENT_COMPATIBLE_COLUMNS)
PROCESS_TYPES = {
    "Breakthrough": "Breakthrough", "Step": "Step", "Pulse Injection": "PulseInjection",
    LWE: "LWE", "Step Elution": "StepElution",
}
ML_MIN = 1e-6 / 60.0
MODEL_CASES = [
    (template, COLUMNS[i % len(COLUMNS)], binding)
    for i, (template, binding) in enumerate(
        itertools.product(INSTRUMENT_TEMPLATES, BINDING_MODELS)
    )
]


def configs_equal(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(configs_equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple, np.ndarray)) or isinstance(b, (list, tuple, np.ndarray)):
        return np.array_equal(np.asarray(a), np.asarray(b))
    return a == b


def run_code(cw):
    namespace = {}
    exec(compile(cw.code(), "<generated>", "exec"), namespace)  # noqa: S102
    return namespace


def assert_code_reproduces(cw):
    namespace = run_code(cw)
    assert configs_equal(
        Cadet().get_process_config(namespace["process"]), Cadet().get_process_config(cw.process)
    )
    return namespace


def names(form):
    return {f.name for f in form.spec.fields}


@pytest.mark.parametrize(("template", "column", "binding"), MODEL_CASES)
def test_selected_models_build_the_matching_process_and_code(configuration, template, column,
                                                             binding):
    cw = configuration
    cw.components = ["Salt", "Protein"]
    cw.select_models(template=template, column=column, binding=binding)

    assert type(cw.process).__name__ == PROCESS_TYPES[template]
    col = cw.process.flow_sheet.column
    assert type(col) is COLUMN_MODELS[column]
    if BINDING_MODELS[binding] is not None:
        assert type(col.binding_model) is BINDING_MODELS[binding]
        assert col.binding_model.component_system is col.component_system
    assert ("sample_loop" in cw.flow_sheet.units_dict) == (template in LOOP_TEMPLATES)
    assert_code_reproduces(cw)


@pytest.mark.parametrize("column", ["Continuous Stirred Tank Reactor (CSTR)", *COLUMNS])
def test_standalone_configuration_builds_and_exports_without_an_instrument(column):
    cw = ConfigurationWidget()
    cw.select_models(column=column, binding="Linear")

    assert "Pulse Feed (Single Component)" in cw._model_picker.option_labels
    assert type(cw.process).__name__ == "Process"
    assert cw.flow_sheet is None
    assert_code_reproduces(cw)


def test_renamed_components_reach_the_column_forms_and_code(configuration):
    configuration.components = ["Salt", "Protein", "Impurity"]
    configuration.select_models(template=LWE, binding="Linear")

    column = configuration.process.flow_sheet.column
    assert column.component_system.names == ["Salt", "Protein", "Impurity"]
    assert configuration.binding_form.spec.fields[0].component_names == (
        "Salt", "Protein", "Impurity")
    fields = {f.name: f for f in configuration._model_form.spec.fields}
    assert fields["c_sample"].component_names == ("Salt", "Protein", "Impurity")
    assert run_code(configuration)["component_system"].names == ["Salt", "Protein", "Impurity"]


def test_code_needs_a_built_process():
    cw = ConfigurationWidget(instrument=InstrumentWidget())
    cw.process = None
    with pytest.raises(RuntimeError, match="(?i)nothing built"):
        cw.code()
    cw.code_view.toggle.value = True
    assert "nothing built" in cw.code_view._body.value.lower()


@pytest.mark.parametrize(("template", "minimum"), [("Breakthrough", 1), (LWE, 2), ("Step", 1)])
def test_template_sets_the_minimum_number_of_components(configuration, template, minimum):
    configuration.select_models(template=template)
    assert len(configuration.components) >= minimum
    assert configuration._components.min_components == minimum


def test_listeners_get_each_valid_build_and_invalid_input_keeps_the_last_one(configuration):
    seen = []
    configuration.add_listener(seen.append)
    element = configuration._model_form.element("flow_rate")

    element.value = 2e-6
    good = configuration.process
    assert seen == [good]

    element.value = -1.0
    assert element.error
    assert configuration.process is good and seen == [good]

    element.value = 3e-6
    assert configuration.process is not good and seen[-1] is configuration.process


def test_cadet_process_rejections_surface_in_the_form_status(configuration):
    configuration.column_form.element("length").value = -1.0

    assert "lower bound" in configuration.column_form.status.value.lower()
    assert configuration.flow_sheet.column.length != -1.0
    configuration._event_sliders["flow_rate"].value *= 2
    assert configuration.process is not None


def test_invalid_system_input_withholds_the_process(bound):
    iw, cw = bound
    iw._sample_loop_checkbox.value = True
    seen = []
    cw.add_listener(seen.append)

    iw._loop_volume_field.value = 0.0
    cw._model_form.element("flow_rate").value = 2e-6
    assert cw.process is None and seen[-1] is None

    iw._loop_volume_field.value = 5e-8
    assert cw.process is not None and seen[-1] is cw.process


@pytest.mark.parametrize("template", list(INSTRUMENT_TEMPLATES))
def test_template_locks_the_sample_loop_only_while_it_needs_one(bound, template):
    iw, cw = bound
    cw.components = ["Salt", "Protein"]
    cw.select_models(template="Step" if template == "Breakthrough" else "Breakthrough")
    builds = []
    cw.add_listener(builds.append)

    cw.select_models(template=template)

    needs_loop = template in LOOP_TEMPLATES
    assert iw._sample_loop_checkbox.value is needs_loop
    assert iw._sample_loop_checkbox.disabled is needs_loop
    assert len(builds) == 1
    assert iw._template_picker.value == template


@pytest.mark.parametrize("user_choice", [False, True])
def test_leaving_a_loop_template_restores_the_users_loop_choice(bound, user_choice):
    iw, cw = bound
    cw.components = ["Salt", "Protein"]
    iw._sample_loop_checkbox.value = user_choice
    cw.select_models(binding=SMA)

    cw.select_models(template=LWE)
    cw.select_models(template="Breakthrough")

    assert iw._sample_loop_checkbox.value is user_choice


def test_instrument_template_picker_selects_the_configuration_template(bound):
    iw, cw = bound
    iw._template_picker.value = "Step"
    assert type(cw.process).__name__ == "Step"


def test_component_edits_on_the_instrument_reach_the_process(bound):
    iw, cw = bound
    iw._components_field.value = ["Salt", "Protein"]
    assert cw.components == ["Salt", "Protein"]
    assert cw.process.component_system.names == ["Salt", "Protein"]


@pytest.mark.parametrize("column", COLUMNS)
def test_column_settings_reshape_the_column_form(configuration, column):
    cw = configuration
    cw.components = ["Salt", "Protein"]
    cw.select_models(column=column, binding="None")
    required = names(cw.column_form)
    multiplexable = [
        n for n, box in cw._multiplex_checkboxes.items() if n in required
    ]
    assert "axial_dispersion" in multiplexable

    for name in multiplexable:
        cw._multiplex_checkboxes[name].value = True
    cw.column_form.element("axial_dispersion").value = [1e-8, 2e-8]
    assert cw.flow_sheet.column.axial_dispersion == [1e-8, 2e-8]

    cw._show_optional_column_checkbox.value = True
    assert {"c", "flow_direction"} <= names(cw.column_form)
    assert not {"q", "discretization"} & names(cw.column_form)
    cw._show_optional_column_checkbox.value = False
    assert names(cw.column_form) == required


@pytest.mark.parametrize(
    ("binding", "optional"),
    [("Linear", set()), ("Langmuir", set()), (SMA, {"reference_liquid_phase_conc"})],
)
def test_binding_form_edits_the_binding_model(configuration, binding, optional):
    cw = configuration
    cw.use_starting_values = False
    cw.select_models(binding=binding)
    required = names(cw.binding_form)
    assert "is_kinetic" in required and not optional & required

    cw.binding_form.element("is_kinetic").value = False
    assert cw.flow_sheet.column.binding_model.is_kinetic is False
    cw._show_optional_binding_checkbox.value = True
    assert optional <= names(cw.binding_form)
    assert cw.process is not None


def test_event_sliders_and_form_fields_stay_linked(configuration):
    cw = configuration
    cw.select_models(template=LWE)
    assert set(cw._event_sliders) == {
        "delta_t_wash", "delta_t_elute", "delta_t_final_wash", "flow_rate_wash",
    }
    slider = cw._event_sliders["delta_t_wash"]
    slider.value = 2 * slider.value
    assert cw._model_form.element("delta_t_wash").value == slider.value
    assert cw.process.flow_sheet is cw.flow_sheet

    element = cw._model_form.element("flow_rate_wash")
    element.value = 10 * cw._event_sliders["flow_rate_wash"].max
    assert cw._event_sliders["flow_rate_wash"].value == pytest.approx(element.value)
    assert cw._event_sliders["flow_rate_wash"].max >= element.value


def test_cycle_time_minutes_field_edits_the_seconds(configuration):
    configuration.select_models(template="Breakthrough")
    configuration._cycle_time_unit_checkbox.value = True
    configuration.components = ["Salt", "Protein"]

    configuration._cycle_time_minutes_element.value = 150.0

    assert configuration.process.cycle_time == 9000.0
    assert configuration._model_form.element("cycle_time").layout.display == "none"


@pytest.mark.parametrize(
    ("template", "phases", "injects"),
    [
        ("Breakthrough", ["Breakthrough"], False),
        ("Step", ["Step"], False),
        ("Pulse Injection", ["Pulse injection"], True),
        (LWE, ["Wash", "Elute (gradient)", "Final wash"], True),
        ("Step Elution", ["Wash", "Elute", "Final wash"], True),
    ],
)
def test_event_timeline_shows_flow_rates_phases_and_injections(configuration, template, phases,
                                                               injects):
    configuration.select_models(template=template)
    chart = configuration._event_chart
    default = PARAMS["flow_rate"].default / ML_MIN

    assert [p["name"] for p in chart.phases] == phases
    assert chart.phases[-1]["end"] == pytest.approx(configuration.process.cycle_time / 60.0)
    assert bool(chart.markers) is injects
    for s in chart.series:
        assert len(s["times"]) == len(s["values"])
        assert max(s["values"]) == pytest.approx(default)

    if template == LWE:
        configuration._model_form.element("delta_t_wash").value = 60.0
        assert chart.phases[0]["end"] == pytest.approx(1.0)


def test_standalone_timeline_plots_concentrations():
    chart = ConfigurationWidget()._event_chart
    assert chart.series and chart.y_label.startswith("Concentration")
    assert chart.phases == []


def test_breakthrough_sample_buffer_choice_feeds_the_chosen_inlet(configuration):
    configuration.select_models(template="Breakthrough")
    sample_buffer = configuration._model_form.element("sample_buffer")

    sample_buffer.value = "A"

    assert configuration.process.flow_sheet.buffer_a.flow_rate[0] > 0


@pytest.mark.parametrize("template", [LWE, "Step Elution"])
def test_wash_elute_buffers_default_to_salt_only(configuration, template):
    configuration.use_starting_values = False
    configuration.components = ["Salt", "Protein", "Impurity"]
    configuration.select_models(template=template)

    values = configuration._model_form.collect_values()
    assert values["c_buffer_a"][1:] == values["c_buffer_b"][1:] == [0.0, 0.0]
    assert all(c > 0 for c in values["c_sample"])


def test_bypassed_column_disables_its_forms_and_keeps_their_values(bound):
    iw, cw = bound
    cw.column_form.element("length").value = 0.123
    before = cw.snapshot()

    iw._unit_checkboxes["column"].value = False
    assert cw._column_picker.disabled and cw._binding_picker.disabled
    assert all(e.disabled for e in cw.column_form._elements.values())
    assert cw.process is not None and "column" not in cw.flow_sheet.units_dict
    cw.column_form.element("length").value = -1.0
    assert cw.process is not None
    cw.column_form.element("length").value = 0.123
    assert cw.snapshot().column_values == before.column_values

    iw._unit_checkboxes["column"].value = True
    assert not cw._column_picker.disabled
    assert cw.flow_sheet.column.length == 0.123

    iw._unit_checkboxes["mixer"].value = True
    assert cw.flow_sheet.column.length == 0.123


def test_standalone_configuration_is_never_bypassed():
    cw = ConfigurationWidget()
    assert not cw._column_picker.disabled
    assert not any(e.disabled for e in cw.column_form._elements.values())


def test_starting_values_fill_a_fresh_sma_setup_and_can_be_switched_off(configuration):
    cw = configuration
    cw.components = ["Salt", "Protein"]
    cw.select_models(template=LWE, binding=SMA)
    state = cw.snapshot()
    assert state.binding_values["capacity"] == 1200.0
    assert state.binding_values["adsorption_rate"] == [0.0, 8.0]
    assert state.model_values["c_buffer_a"] == [50.0, 0.0]
    assert state.column_values["c"] == [50.0, 0.0]

    cw.select_models(template="Pulse Injection")
    assert cw.snapshot().model_values["c_buffer_a"] == [400.0, 0.0]

    cw.use_starting_values = False
    cw.select_models(template=LWE)
    assert cw.snapshot().model_values["c_buffer_a"] != [50.0, 0.0]
    cw.use_starting_values = True
    assert cw.snapshot().model_values["c_buffer_a"] == [50.0, 0.0]


def test_switched_off_starting_values_keep_plain_defaults():
    cw = ConfigurationWidget(instrument=InstrumentWidget(), starting_values=False)
    cw.components = ["Salt", "Protein"]
    cw.select_models(template=LWE, binding=SMA)
    assert cw.snapshot().binding_values["capacity"] == 0.0


@pytest.mark.parametrize("starting", [True, False])
def test_reset_restores_starting_values_or_plain_defaults(configuration, starting):
    cw = configuration
    cw.components = ["Salt", "Protein"]
    cw.select_models(template=LWE, binding=SMA)
    cw.use_starting_values = starting

    cw.binding_form.element("capacity").value = 500.0
    cw._model_form.element("c_buffer_a").value = [123.0, 0.0]
    cw.column_form.element("length").value = 0.2
    for form in (cw.binding_form, cw._model_form, cw.column_form):
        form._on_reset(None)

    state = cw.snapshot()
    assert state.binding_values["capacity"] == (1200.0 if starting else 0.0)
    assert state.model_values["c_buffer_a"] == ([50.0, 0.0] if starting else [20.0, 0.0])
    assert state.column_values["length"] == 0.05
    assert cw.process is not None


@pytest.mark.parametrize(
    "unrelated_change",
    [
        lambda iw, cw: setattr(cw._show_optional_binding_checkbox, "value", True),
        lambda iw, cw: setattr(iw._unit_checkboxes["mixer"], "value", True),
    ],
    ids=["optional-binding", "instrument-unit"],
)
def test_edited_method_values_survive_unrelated_changes(bound, unrelated_change):
    iw, cw = bound
    cw.components = ["Salt", "Protein"]
    cw.select_models(template="Pulse Injection", binding=SMA)
    cw._model_form.element("c_buffer_a").value = [123.0, 0.0]

    unrelated_change(iw, cw)

    assert cw.snapshot().model_values["c_buffer_a"] == [123.0, 0.0]
    cw.select_models(template=LWE)
    assert cw.snapshot().model_values["c_buffer_a"] == [50.0, 0.0]


def assert_signal_inside_the_cycle(process, unit, port):
    from cadetgui.process_model.simulation import run_process

    solution = run_process(process).solution[unit][port]
    signal = np.asarray(solution.solution).reshape(len(solution.time), -1)[:, -1]
    change = signal - signal[0]
    peak = change.max()
    t_99 = float(np.asarray(solution.time)[np.argmax(change >= 0.99 * peak)])
    assert peak > 1e-2
    assert t_99 < 0.9 * process.cycle_time
    assert change[-1] / peak < 0.05 or change[-1] / peak > 0.95


@pytest.mark.slow
@pytest.mark.parametrize("template", list(INSTRUMENT_TEMPLATES))
def test_default_template_signal_peaks_or_breaks_through_inside_the_cycle(configuration,
                                                                          template):
    configuration.select_models(template=template)
    assert_signal_inside_the_cycle(configuration.process, "outlet", "inlet")


@pytest.mark.slow
@pytest.mark.parametrize("type_id", list(EXPERIMENT_TYPES))
def test_experiment_type_signal_peaks_or_breaks_through_inside_the_cycle(type_id):
    from cadetgui.characterization.guide import with_implied_values
    from cadetgui.characterization.parameter_store import ParameterStore, apply_store
    from cadetgui.instrument.process_builder import build_process
    from cadetgui.widgets.benches import CharacterizationWorkbenchWidget

    experiment = EXPERIMENT_TYPES[type_id]
    base = CharacterizationWorkbenchWidget().configuration.snapshot()
    process = build_process(experiment.apply(base, component="Probe"))
    apply_store(process, with_implied_values(ParameterStore(), experiment, "Probe"))
    unit, port = experiment.solution_path.split(".")[:2]
    assert_signal_inside_the_cycle(process, unit, port)


def test_flow_rate_section_sets_and_follows_the_configuration_flow_rate(configuration):
    from cadetgui.widgets.instrument import FlowRateSection

    section = FlowRateSection(configuration, note="Shared")
    assert float(section.field.value) == pytest.approx(PARAMS["flow_rate"].default / ML_MIN)

    section.field.value = "2"
    assert configuration.snapshot().model_values["flow_rate"] == pytest.approx(2 * ML_MIN)
    section.field.value = "-1"
    assert section.field.error and configuration.flow_rate == pytest.approx(2 * ML_MIN)

    configuration.set_flow_rate(None)
    configuration._model_form.element("flow_rate").value = 3 * ML_MIN
    assert float(section.field.value) == pytest.approx(3)


@pytest.mark.parametrize("template", ["Step", "Pulse Injection"])
def test_template_editor_gives_the_process_the_templates_events(configuration, template):
    from cadetgui.widgets.instrument import TemplateEditor
    from CADETProcess.processModel import Process

    configuration.select_models(template="Pulse Injection")
    process = Process(configuration.flow_sheet, "edited")
    changes = []
    editor = TemplateEditor(process, lambda: changes.append(len(process.events)))

    editor.picker.value = template
    editor.form.element("flow_rate").value = 2 * ML_MIN

    assert changes and process.events
    namespace = {"flow_sheet": configuration.flow_sheet}
    exec(editor.code(), namespace)  # noqa: S102
    assert namespace["process"].cycle_time == process.cycle_time
