"""Process templates, recipes, starting values and the headless process builder."""
from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest
from cadetgui.instrument import process_builder
from cadetgui.instrument.process_builder import build_process, check_recipe
from cadetgui.instrument.recipes import (
    recipe_flow_rate,
    recipe_template_fields,
    recipe_with_template,
    template_options,
)
from cadetgui.instrument.signals import measurable_signal_options
from cadetgui.instrument.starting_values import (
    binding_starting_values,
    starting_values,
    with_starting_values,
)
from cadetgui.instrument.system import (
    BINDING_MODELS,
    INSTRUMENT_COMPATIBLE_COLUMNS,
    active_inlets,
    inlet_contents,
)
from cadetgui.instrument.templates import (
    INSTRUMENT_TEMPLATES,
    process_phase_spans,
    sample_injection_times,
    template_required_units,
)
from cadetgui.io.configuration_store import ConfigurationState, InstrumentState
from cadetgui.parameters.specs import (
    build_parameter_config_spec,
    parse_float_list,
    require_finite_above,
)
from CADETProcess.processModel import ComponentSystem, Langmuir
from CADETProcess.simulator import Cadet

SMA = "Steric Mass Action (SMA)"
LWE = "Load–Wash–Elute (LWE)"
LRM = "Lumped Rate Model Without Pores (LRM)"
TEMPLATES = list(INSTRUMENT_TEMPLATES)
LOOP_TEMPLATES = ["Pulse Injection", LWE, "Step Elution"]
PHASES = {
    "Breakthrough": 1, "Step": 1, "Pulse Injection": 1, LWE: 3, "Step Elution": 3,
}


def recipe(template=LWE, column=LRM, binding="Linear", components=("Salt", "Protein"), **kw):
    loop = template in LOOP_TEMPLATES
    instrument = kw.pop("instrument", InstrumentState(include_sample_loop=loop))
    return ConfigurationState(
        components=list(components), column_key=column, binding_key=binding,
        template_key=template, instrument=instrument, **kw,
    )


def configs_equal(a, b):
    """Compare two `Cadet().get_process_config()` trees, array-safe."""
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(configs_equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple, np.ndarray)) or isinstance(b, (list, tuple, np.ndarray)):
        return np.array_equal(np.asarray(a), np.asarray(b))
    return a == b


def cadet_config(process):
    return Cadet().get_process_config(process)


@pytest.mark.parametrize("template", TEMPLATES)
@pytest.mark.parametrize("column", sorted(INSTRUMENT_COMPATIBLE_COLUMNS))
@pytest.mark.parametrize("binding", list(BINDING_MODELS))
def test_every_recipe_builds_a_well_posed_process(template, column, binding):
    process = build_process(recipe(template, column, binding))

    flow_sheet = process.flow_sheet
    assert ("sample_loop" in flow_sheet.units_dict) == (template in LOOP_TEMPLATES)
    col = flow_sheet.column
    if binding != "None":
        assert col.binding_model.component_system is col.component_system
    for name in ("bed_porosity", "particle_porosity", "total_porosity"):
        if name in col.required_parameters:
            assert 0 < getattr(col, name) < 1, name
    assert col.length > 0 and col.diameter > 0
    assert active_inlets(process)
    assert set(inlet_contents(process)) >= set(active_inlets(process))


@pytest.mark.parametrize("template", TEMPLATES)
def test_template_phases_injections_and_required_units(template):
    process = build_process(recipe(template))

    spans = process_phase_spans(process)
    assert len(spans) == PHASES[template] or (spans == [] and PHASES[template] == 1)
    if spans:
        assert spans[0]["start"] == 0.0
        assert spans[-1]["end"] == pytest.approx(process.cycle_time)
        assert all(a["end"] == b["start"] for a, b in zip(spans, spans[1:]))
    assert bool(sample_injection_times(process)) == (template in LOOP_TEMPLATES)
    required = template_required_units(INSTRUMENT_TEMPLATES[template])
    assert required == ({"sample_loop"} if template in LOOP_TEMPLATES else set())


def test_process_phase_spans_names_apply_only_one_per_phase():
    process = build_process(recipe(LWE))
    names = ["a", "b", "c"]
    assert [s["name"] for s in process_phase_spans(process, names)] == names
    assert [s["name"] for s in process_phase_spans(process, ["x"])][0] == "Phase 1"


def test_measurable_signals_skip_infrastructure_and_undriven_inlets():
    process = build_process(recipe("Pulse Injection", instrument=InstrumentState(
        include_sample_loop=True, bypass_units=[],
    )))
    labels = [label for label, _ in measurable_signal_options(process)]

    assert labels[0] == "Outlet"
    assert {"Column outlet", "Column inlet"} <= set(labels)
    assert not any(label.startswith(("Mixer", "Sample loop", "Buffer C")) for label in labels)


@pytest.mark.parametrize(
    "instrument",
    [
        InstrumentState(include_sample_loop=True),
        InstrumentState(
            include_sample_loop=True, sample_loop_diameter_auto=False,
            sample_loop_diameter=1e-3, sample_loop_volume=80e-9, bypass_units=["mixer"],
            unit_values={"tubing_pre_column": {"length": 0.3}},
        ),
        InstrumentState(include_sample_loop=True, bypass_units=["column"]),
    ],
    ids=["default", "loop-and-tubing", "no-column"],
)
def test_build_process_matches_the_widget_that_saved_the_recipe(bound, instrument):
    iw, cw = bound
    cw._apply_state("saved", replace(cw.snapshot(), template_key="Pulse Injection",
                                     instrument=instrument))
    assert configs_equal(cadet_config(cw.process), cadet_config(build_process(cw.snapshot())))


def test_build_process_matches_a_standalone_configuration():
    from cadetgui.widgets.instrument import ConfigurationWidget

    cw = ConfigurationWidget()
    cw.select_models(binding="Langmuir")
    assert configs_equal(cadet_config(cw.process), cadet_config(build_process(cw.snapshot())))


def test_overrides_replace_method_values_only():
    state = recipe("Breakthrough")
    overridden = build_process(state, overrides={"flow_rate": 5e-6})

    assert next(e for e in overridden.events if e.name == "phase_0_F").state == 5e-6
    assert "flow_rate" not in state.model_values


@pytest.mark.parametrize("field", ["column_key", "binding_key", "template_key"])
@pytest.mark.parametrize("standalone", [False, True])
def test_unregistered_keys_are_rejected(field, standalone):
    state = recipe("Breakthrough")
    if standalone:
        state = replace(state, instrument=None, template_key="Pulse Feed (Single Component)")
    with pytest.raises(ValueError, match=field.split("_")[0]):
        build_process(replace(state, **{field: "Not registered"}))


def test_check_recipe_builds_once_per_content_and_reports_errors(monkeypatch):
    state = recipe("Breakthrough")
    process_builder.clear_recipe_checks()
    calls = []
    original = process_builder.build_process
    monkeypatch.setattr(
        process_builder, "build_process", lambda *a, **k: calls.append(a) or original(*a, **k)
    )

    check = check_recipe(state)
    assert check_recipe(replace(state)) is check and len(calls) == 1
    assert check.error is None and "column" in check.units
    assert check.species == tuple(state.components) and check.signal_options
    assert check.has_parameter("flow_sheet.column.length")
    assert not check.has_parameter("flow_sheet.column.nope")
    check_recipe(state, {"flow_rate": 5e-6})
    assert len(calls) == 2

    broken = check_recipe(replace(state, column_key="Not registered"))
    assert "column" in broken.error and not broken.has_parameter("flow_sheet.column.length")


@pytest.mark.parametrize("template", TEMPLATES)
def test_recipe_with_template_keeps_the_flow_rate_and_adds_a_required_loop(template):
    base = recipe("Breakthrough", instrument=InstrumentState(), model_values={"flow_rate": 3e-8})

    changed = recipe_with_template(base, template)

    assert changed.template_key == template
    assert recipe_flow_rate(changed) == 3e-8
    assert set(changed.model_values) == {f.name for f in recipe_template_fields(changed)}
    assert changed.instrument.include_sample_loop == (template in LOOP_TEMPLATES)
    build_process(changed)


def test_template_options_keep_an_unavailable_template():
    options = template_options(recipe(template="Removed"))
    assert [k for _, k in options] == [*TEMPLATES, "Removed"]
    assert "not available" in options[-1][0]


def test_sma_starting_values_fill_unset_values_and_keep_edits():
    start = starting_values()["binding"][SMA]
    seeded = binding_starting_values(SMA, ["Salt", "A", "B"], {
        "capacity": 0.0, "characteristic_charge": [0.0, 3.0, 0.0],
        "adsorption_rate": [0.0, 0.0, 0.0], "is_kinetic": True,
    })
    assert seeded["capacity"] == start["scalar"]["capacity"]
    charge = start["per_component"]["characteristic_charge"]
    assert seeded["characteristic_charge"] == [0.0, 3.0, charge]
    assert seeded["adsorption_rate"][0] == 0.0
    edited = {"adsorption_rate": [0.0, 2.0], "reference_liquid_phase_conc": 1.0}
    assert binding_starting_values(SMA, ["Salt", "P"], edited)["reference_liquid_phase_conc"] == 1.0
    untouched = {"adsorption_rate": [0.0], "desorption_rate": [0.0], "is_kinetic": True}
    assert binding_starting_values("Linear", ["A"], untouched) == untouched


def test_with_starting_values_follows_the_template_and_equilibrates_the_column():
    base = recipe(LWE, "Lumped Rate Model With Pores (LRMP)", SMA,
                  model_values={"c_buffer_a": [50.0, 0.0]}, column_values={"c": [10.0, 0.0]})
    seeded = with_starting_values(base)
    assert seeded.model_values["c_sample"] == [50.0, 1.0]
    assert seeded.column_values["c"] == seeded.column_values["cp"] == [50.0, 0.0]
    assert with_starting_values(replace(base, template_key="Pulse Injection")).model_values[
        "c_buffer_a"] == [400.0, 0.0]

    binding_only = with_starting_values(base, method=False)
    assert binding_only.model_values == base.model_values
    assert binding_only.binding_values["capacity"] == 1200.0
    assert with_starting_values(base, method=False, equilibrate=False).column_values == {
        "c": [10.0, 0.0]}
    linear = replace(base, binding_key="Linear")
    assert with_starting_values(linear) is linear


def test_every_listed_starting_method_names_real_template_fields():
    from types import SimpleNamespace

    stub = SimpleNamespace(component_system=ComponentSystem(["Salt", "Protein"]))
    for entry in starting_values()["binding"].values():
        for template, method in entry.get("methods", {}).items():
            fields = {f.name for f in INSTRUMENT_TEMPLATES[template](stub).fields}
            assert set(method) - {"note"} <= fields, template


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1, 2;3\n4 5", [1.0, 2.0, 3.0, 4.0, 5.0]), ("  ", []), ((1, "2"), [1.0, 2.0]),
        ("1, abc", None),
    ],
)
def test_parse_float_list(raw, expected):
    if expected is None:
        with pytest.raises(ValueError):
            parse_float_list(raw)
    else:
        assert parse_float_list(raw) == expected


@pytest.mark.parametrize(
    ("kwargs", "value", "ok"),
    [
        ({}, 0.0, False), ({"inclusive": True}, 0.0, True), ({"minimum": 1.0}, 0.5, False),
        ({}, math.nan, False), ({}, math.inf, False), ({}, 3.0, True),
    ],
)
def test_require_finite_above(kwargs, value, ok):
    validate = require_finite_above(**kwargs)
    if ok:
        validate(value)
    else:
        with pytest.raises(ValueError):
            validate(value)


def test_parameter_spec_has_a_stable_field_order_and_builds_the_object():
    binding = Langmuir(ComponentSystem(["A", "B"]), name="binding")
    spec = build_parameter_config_spec(binding)

    assert [f.name for f in spec.fields] == [*sorted(binding.required_parameters), "is_kinetic"]
    assert next(f for f in spec.fields if f.name == "capacity").component_names == ("A", "B")
    spec.build({"capacity": "1.5, 2.5", "is_kinetic": False})
    assert list(binding.capacity) == [1.5, 2.5] and binding.is_kinetic is False
