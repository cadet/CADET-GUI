"""Step readiness: the live pre-run checks and the per-step status of a study."""
from __future__ import annotations

from dataclasses import replace

import pytest
from cadetgui.characterization.guide import guide_for_step
from cadetgui.characterization.parameter_store import ParameterStore
from cadetgui.characterization.step_checks import (
    CONFIRM_KNOWN,
    KNOWN_HARDWARE,
    confirm_known_value,
    known_value_label,
    quantity_text,
    step_checks,
    study_steps_status,
)

from characterization.synthetic import DISPERSION, FILM

DIAMETER = "flow_sheet.tubing_pre_column.diameter"


def checks_by_id(study, index=0):
    return {c.id: c for c in step_checks(study, study.steps[index])}


def drop_entry(study, path):
    store = study.initial_store
    study.initial_store = ParameterStore(
        specs=store.specs, entries={k: v for k, v in store.entries.items() if k != path},
        step=store.step,
    )


def test_status_before_and_after_accepting_the_first_step(study, accept_periphery):
    assert [guide_for_step(s).id for s in study.steps] == ["system_periphery", "column_packing"]
    first, second = study_steps_status(study)
    assert first.ready and not first.accepted and first.next_action == "Run the fit."
    assert first.measurements == {"system_pulse": ["System pulse 1 (UV)", "System pulse 2 (UV)"]}
    assert set(second.measurements) == {"column_pulse_small_tracer", "column_pulse_large_tracer"}
    assert not second.ready
    assert second.next_action.endswith("accept Extra-column volume first.")
    fitted = study_steps_status(study, fitted={"Extra-column volume"})[0]
    assert fitted.next_action == "Choose a Pareto candidate and accept it."

    accept_periphery()

    first, second = study_steps_status(study)
    assert first.accepted and first.next_action == "Accepted. Continue with Column packing."
    assert second.species_gaps == {DISPERSION: ["SmallTracer", "LargeTracer"]}
    assert any(
        "Column packing needs axial dispersion (Tubing (pre column)) for SmallTracer, "
        "LargeTracer; Extra-column volume fitted it for SystemTracer" in p
        for p in second.problems
    )


def test_a_role_mismatch_blocks_the_step(study):
    study.set_component_role("SmallTracer", "protein")
    status = study_steps_status(study)[1]
    assert not status.ready
    assert any("declared as a protein" in p for p in status.problems)


def test_the_example_step_passes_with_replicates_and_markers(study):
    checks = checks_by_id(study)
    assert checks["measurements"].status == "ok" and "replicates" in checks["measurements"].text
    assert checks["markers"].status == "ok"
    assert checks[f"known:{DIAMETER}"].status == "ok"


def test_a_single_measurement_asks_for_a_replicate(study):
    study.upsert_step(replace(study.steps[0], comparisons=study.steps[0].comparisons[:1]))
    check = checks_by_id(study)["measurements"]
    assert check.status == "info" and "replicate" in check.text
    assert check.actions[0].target == "measurements"


def test_broken_measurements_link_to_themselves(study):
    for name, change in (("System pulse 2 (UV)", {"injection_marker": "Phase Nope"}),
                         ("System pulse 1 (UV)", {"baseline_window": (1e6, 2e6)})):
        study.replace_comparison(name, replace(study.comparison(name), **change))
    checks = checks_by_id(study)
    marker = checks["marker:System pulse 2 (UV)"]
    assert marker.status == "warn" and "'Phase Nope' not found in the run log" in marker.text
    assert "problems:System pulse 2 (UV)" not in checks
    baseline = checks["problems:System pulse 1 (UV)"]
    assert "No points in the baseline fitting window" in baseline.text
    assert baseline.actions[0].context == {"select": "System pulse 1 (UV)"}


def test_values_the_experiment_types_assume_must_be_recorded(study, accept_periphery):
    entry = study.initial_store.entries[FILM]
    entries = dict(study.initial_store.entries)
    entries[FILM] = replace(entry, value={"SmallTracer": entry.value["SmallTracer"]})
    study.initial_store = replace(study.initial_store, entries=entries)
    accept_periphery()

    status = study_steps_status(study)[1]
    assert status.next_action.startswith("The experiment types assume values")
    assert all("film_diffusion" not in path for path in status.species_gaps)
    assumptions = checks_by_id(study, 1)["assumptions"]
    assert "film diffusion (Column) = 0 for LargeTracer" in assumptions.text


@pytest.mark.parametrize("value, note", [(0.5e-3, "confirmed default"), (0.75e-3, KNOWN_HARDWARE)])
def test_a_default_hardware_value_is_a_note_until_confirmed(study, accept_periphery, value, note):
    drop_entry(study, DIAMETER)
    accept_periphery()
    check = checks_by_id(study)[f"known:{DIAMETER}"]
    assert check.status == "info"
    assert check.text == (
        "Pre-column tubing diameter: using the default 0.5 mm. Is that your hardware?"
    )
    assert [a.target for a in check.actions] == [CONFIRM_KNOWN, "system"]
    assert study_steps_status(study)[0].accepted

    confirm_known_value(study, DIAMETER, value, note)

    entry = study.initial_store.entries[DIAMETER]
    assert entry.value == pytest.approx(value)
    assert (entry.provenance.step, entry.provenance.note) == ("initial", note)
    assert entry.provenance.source == KNOWN_HARDWARE
    assert study.posteriors["Extra-column volume"].entries[DIAMETER].value == pytest.approx(value)
    assert checks_by_id(study)[f"known:{DIAMETER}"].status == "ok"


@pytest.mark.parametrize("value, unit, text", [
    (0.5e-3, r"\mathrm{m}", "0.5 mm"),
    (5e-6, r"\mathrm{m}", "5 µm"),
    (1.2, r"\frac{\mathrm{mol}}{\mathrm{m}^{3}}", "1.2 mol/m³"),
])
def test_hardware_values_read_in_lab_units(value, unit, text):
    assert quantity_text(value, unit)[0] == text


@pytest.mark.parametrize("path, label", [
    (DIAMETER, "Pre-column tubing diameter"),
    ("flow_sheet.column.length", "Column length"),
    ("flow_sheet.column.binding_model.capacity", "Ionic capacity"),
])
def test_known_value_labels(path, label):
    assert known_value_label(path) == label
