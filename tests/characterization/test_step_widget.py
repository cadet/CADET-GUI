"""CharacterizationStepWidget: setup written to the study, checks, run, candidates, accept."""
from __future__ import annotations

import csv
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from cadetgui.characterization import runner as characterization_runner
from cadetgui.characterization.comparison import Comparison
from cadetgui.characterization.guide import CHAIN_BY_ID, new_step_setup
from cadetgui.characterization.parameter_store import Provenance
from cadetgui.characterization.runner import (
    AVERAGE_TAG,
    Candidate,
    StepResult,
    StepSetup,
    build,
)
from cadetgui.characterization.study import Study
from cadetgui.widgets.characterization import (
    CharacterizationStepWidget,
    ComparisonsWidget,
    ParameterStoreWidget,
)

from characterization.synthetic import DISPERSION, LENGTH

DIAMETER = "flow_sheet.tubing_pre_column.diameter"


@pytest.fixture
def periphery(study) -> CharacterizationStepWidget:
    return CharacterizationStepWidget(study, "Extra-column volume")


def pulse_copy(study: Study, name: str, source: str = "System pulse 1 (UV)"):
    return replace(study.comparison(source), name=name)


def fake_result(widget: CharacterizationStepWidget) -> StepResult:
    setup = widget.get_value()
    built = build(setup, widget.study.prior_for(setup.name))
    return StepResult(
        step=setup.name, variable_names=list(built.problem.independent_variable_names),
        objective_names=setup.objective_names,
        x=np.array([[0.42, 4.5e-7], [0.6, 2e-6], [0.3, 1e-7]]),
        f=np.array([[0.05, 0.06], [0.2, 0.01], [0.01, 0.3]]),
        success=True, message="Optimization finished.", cancelled=False,
        optimizer_name="U-NSGA-III", built=built,
    )


class FakeOptimizer:
    """The part of a running optimizer the progress ticker reads."""

    def __init__(self) -> None:
        self.results = SimpleNamespace(populations=[], pareto_fronts=[], meta_front=None)

    def add_generation(self, x, f) -> None:
        f = np.asarray(f, dtype=float)
        self.results.populations.append(SimpleNamespace(f_min=f.min(axis=0)))
        front = SimpleNamespace(x_independent=np.asarray(x, dtype=float), f=f)
        self.results.pareto_fronts.append(front)
        self.results.meta_front = front


GENERATIONS = [
    ([[0.3, 1e-7], [0.6, 2e-6]], [[0.4, 0.5], [0.3, 0.2]]),
    ([[0.42, 4.5e-7], [0.6, 2e-6]], [[0.05, 0.06], [0.3, 0.2]]),
    ([[0.42, 4.5e-7], [0.41, 4e-7]], [[0.05, 0.06], [0.04, 0.05]]),
    ([[0.42, 4.5e-7], [0.41, 4e-7]], [[0.05, 0.06], [0.04, 0.05]]),
]


@pytest.fixture
def stub_run(monkeypatch, periphery):
    """Replace `runner.run` by one yielding GENERATIONS; spy on live-plot evaluations."""
    result = fake_result(periphery)

    def run(setup, store, *, on_optimizer_ready, cancel_event, **_kwargs):
        optimizer = FakeOptimizer()
        on_optimizer_ready(optimizer)
        for x, f in GENERATIONS:
            time.sleep(0.15)
            optimizer.add_generation(x, f)
        time.sleep(0.15)
        return result

    monkeypatch.setattr(characterization_runner, "run", run)
    periphery._TICK_SECONDS = 0.02
    spy = SimpleNamespace(active=0, max_active=0, live_calls=0, lock=threading.Lock())
    evaluate = Comparison.evaluate

    def slow_evaluate(comparison, store):
        live = threading.current_thread().name == "live-fit-plot"
        if live:
            with spy.lock:
                spy.active += 1
                spy.live_calls += 1
                spy.max_active = max(spy.max_active, spy.active)
            time.sleep(0.2)
        try:
            return evaluate(comparison, store)
        finally:
            if live:
                with spy.lock:
                    spy.active -= 1

    monkeypatch.setattr(Comparison, "evaluate", slow_evaluate)
    return periphery, result, spy


def show_result(widget: CharacterizationStepWidget, result: StepResult) -> None:
    widget._run_setup = widget.get_value()
    widget._run_prior = widget.study.prior_for(widget.step_name)
    widget._progress = {"result": result}
    widget.form.set_locked(True)
    widget._finish(time.monotonic())


class TestSetup:
    def test_shows_the_step_without_touching_the_study(self, study):
        before = list(study.steps)
        widget = CharacterizationStepWidget(study, "Extra-column volume")
        form = widget.form
        assert all(a is b for a, b in zip(study.steps, before)) and len(study.steps) == 2
        assert (form.name.value, form.stage.value) == ("Extra-column volume", "tubing")
        assert form.selected_names() == ["System pulse 1 (UV)", "System pulse 2 (UV)"]
        lb, ub = form._bound_fields["tubing_pre_column_length"]
        assert (lb.value, ub.value) == (0.1, 1.0)
        assert widget.get_value().bounds == study.steps[0].bounds
        assert widget.guide is CHAIN_BY_ID["system_periphery"] and form.guided

    def test_edits_upsert_the_step_and_notify(self, periphery, study):
        notified = []
        periphery.add_listener(lambda: notified.append(1))
        lb, _ = periphery.form._bound_fields["tubing_pre_column_length"]
        lb.value = 0.2
        periphery.form._fit_boxes["tubing_pre_column_axial_dispersion"].value = False

        step = study.steps[0]
        assert step.bounds["tubing_pre_column_length"] == (0.2, 1.0)
        assert step.frozen == ("tubing_pre_column_axial_dispersion",)
        assert step.provides == [LENGTH]
        assert len(study.steps) == 2 and notified
        periphery.form._fit_boxes["tubing_pre_column_axial_dispersion"].value = True
        assert study.steps[0].frozen == ()

    def test_follows_step_changes_made_elsewhere(self, periphery, study):
        study.upsert_step(replace(study.steps[0], bounds={"tubing_pre_column_length": (0.3, 0.9)}))
        lb, ub = periphery.form._bound_fields["tubing_pre_column_length"]
        assert (lb.value, ub.value) == (0.3, 0.9)
        study.steps[0].frozen = ("tubing_pre_column_length",)
        form = CharacterizationStepWidget(study, "Extra-column volume").form
        assert not form._fit_boxes["tubing_pre_column_length"].value

    def test_rename_keeps_position_and_posterior_and_refuses_clashes(
        self, periphery, study, accept_periphery
    ):
        accept_periphery()
        periphery.form.name.value = "Column packing"
        assert "already called" in periphery.status.value
        periphery.form.name.value = "periphery"
        assert [s.name for s in study.steps] == ["periphery", "Column packing"]
        assert set(study.posteriors) == {"periphery"}

    def test_a_new_step_is_appended_on_first_edit(self, study):
        widget = CharacterizationStepWidget(study)
        assert widget.step_name == "step_3" and len(study.steps) == 2
        widget.form.stage.value = "bed"
        assert study.steps[-1].name == "step_3" and study.steps[-1].stage == "bed"

    def test_stage_options_drive_the_variables_and_choices(self, study):
        widget = CharacterizationStepWidget(study, "Column packing")
        form = widget.form
        form._option_fields["include_particle_porosity"].value = False
        assert "particle_porosity" not in form._bound_fields
        assert study.steps[1].options == {"include_particle_porosity": False}

        form.stage.value = "tubing"
        assert form._option_fields["tubing"].option_labels == ["Tubing (pre column)"]
        for name in ("Large tracer pulse 1 (UV)", "Large tracer pulse 2 (UV)"):
            form._comparison_boxes[name].value = False
        assert form._option_fields["tubing"].option_labels == [
            "Tubing (pre column)", "Tubing (detectors)",
        ]
        form.stage.value = "particles"
        assert form._option_fields["component_index"].option_labels == ["SmallTracer"]

    def test_optimizer_choice_and_knobs_are_part_of_the_step(self, periphery, study):
        form = periphery.form
        assert form.optimizer.option_labels == ["U-NSGA-III"]
        assert [f.value for f in form._knob_fields["U-NSGA-III"]] == [16, 12]
        form._knob_fields["U-NSGA-III"][1].value = 9
        assert study.steps[0].optimizer["knobs"] == {"pop_size": 16, "n_max_gen": 9}

        form._comparison_boxes["System pulse 2 (UV)"].value = False
        assert set(form.optimizer.option_labels) == {"Nelder-Mead", "U-NSGA-III"}
        form.optimizer.value = "Nelder-Mead"
        assert form._knob_fields["Nelder-Mead"][0].value == 400
        form._fit_boxes["tubing_pre_column_axial_dispersion"].value = False
        assert form._knob_fields["Nelder-Mead"][0].value == 200
        form._knob_fields["Nelder-Mead"][0].value = 25
        form._fit_boxes["tubing_pre_column_axial_dispersion"].value = True
        assert study.steps[0].optimizer == {"name": "Nelder-Mead", "knobs": {"maxiter": 25}}

    def test_loaded_knobs_that_differ_from_the_sizing_are_kept(self, study):
        study.steps[0].optimizer = {"name": "U-NSGA-III", "knobs": {"pop_size": 6, "n_max_gen": 12}}
        form = CharacterizationStepWidget(study, "Extra-column volume").form
        form.stage.value = "adsorption"
        form._option_fields["is_kinetic"].value = True
        assert [f.value for f in form._knob_fields["U-NSGA-III"]] == [6, 12]
        assert [f.value for f in form._knob_fields["Nelder-Mead"]] == [600]

    def test_current_values_come_from_the_process_or_the_accepted_step(
        self, study, accept_periphery
    ):
        pulses = [c for c in study.comparisons if c.experiment_type == "system_pulse"]
        study.upsert_step(StepSetup(name="Refit tubing", stage="tubing",
                                    options={"tubing": "tubing_pre_column"}, comparisons=pulses))
        widget = CharacterizationStepWidget(study, "Refit tubing")
        cell = widget.form._current_cells["tubing_pre_column_length"]
        assert cell.value == "0.1 m<br><small>from the process setup</small>"
        accept_periphery()
        assert cell.value == "0.42 m<br><small>from Extra-column volume</small>"


class TestMeasurementSelection:
    def test_exclusions_persist_and_new_fitting_measurements_are_included(self, study, tmp_path):
        widget = CharacterizationStepWidget(study, "Extra-column volume")
        assert list(widget.form._comparison_boxes) == ["System pulse 1 (UV)", "System pulse 2 (UV)"]
        widget.form._comparison_boxes["System pulse 2 (UV)"].value = False
        assert study.steps[0].excluded == ("System pulse 2 (UV)",)

        study.upsert_comparison(pulse_copy(study, "System pulse 3 (UV)"))
        study.upsert_comparison(pulse_copy(study, "Small 3", "Small tracer pulse 1 (conductivity)"))
        assert study.steps[0].objective_names == ["System pulse 1 (UV)", "System pulse 3 (UV)"]
        assert "Small 3" not in study.steps[1].objective_names

        reloaded = Study.load(study.save(tmp_path / "study.json"))
        boxes = CharacterizationStepWidget(reloaded, "Extra-column volume").form._comparison_boxes
        assert not boxes["System pulse 2 (UV)"].value and boxes["System pulse 3 (UV)"].value
        boxes["System pulse 2 (UV)"].value = True
        assert reloaded.steps[0].excluded == ()

    @pytest.mark.parametrize("excluded, objectives", [
        (None, ["System pulse 1 (UV)"]),
        ((), ["System pulse 1 (UV)", "System pulse 2 (UV)"]),
    ])
    def test_a_loaded_step_keeps_only_recorded_exclusions(self, study, excluded, objectives):
        step = study.steps[0]
        study.upsert_step(replace(step, comparisons=step.comparisons[:1], excluded=excluded))
        widget = CharacterizationStepWidget(study, "Extra-column volume")
        assert not widget.form._comparison_boxes["System pulse 2 (UV)"].value
        study.notify()
        assert study.steps[0].objective_names == objectives

    def test_a_custom_step_offers_every_measurement_and_includes_none(self, study):
        study.upsert_step(StepSetup(name="mine", stage="bed",
                                    options={"include_particle_porosity": False}))
        widget = CharacterizationStepWidget(study, "mine")
        assert not widget.form.guided
        assert list(widget.form._comparison_boxes) == [c.name for c in study.comparisons]
        study.upsert_comparison(pulse_copy(study, "System pulse 3 (UV)"))
        assert "System pulse 3 (UV)" in widget.form._comparison_boxes
        assert study.steps[-1].comparisons == []

    def test_a_member_that_does_not_fit_can_be_removed(self, study):
        legacy = [*study.steps[0].comparisons, study.comparison("Large tracer pulse 1 (UV)")]
        study.upsert_step(replace(study.steps[0], comparisons=legacy))
        widget = CharacterizationStepWidget(study, "Extra-column volume")
        box = widget.form._comparison_boxes["Large tracer pulse 1 (UV)"]
        assert box.value
        box.value = False
        widget.form.refresh_comparisons()
        assert "Large tracer pulse 1 (UV)" not in widget.form._comparison_boxes
        assert "Large tracer pulse 1 (UV)" not in study.steps[0].objective_names

    def test_no_fitting_measurement_offers_to_add_one(self, study, navigation):
        study.upsert_step(new_step_setup(CHAIN_BY_ID["particle_transport"], []))
        widget = CharacterizationStepWidget(study, "Particle transport", on_navigate=navigation)
        assert widget.form._comparison_boxes == {}
        widget.form._btn_add_measurement.click()
        assert navigation.calls == [("measurements", {"step_id": "particle_transport"})]


class TestChecks:
    @pytest.mark.parametrize("change, message", [
        ({"channel": "nope"}, "Unknown channel"),
        (None, "at least one measurement"),
    ])
    def test_problems_block_the_run(self, study, change, message):
        if change:
            name = "System pulse 2 (UV)"
            study.replace_comparison(name, replace(study.comparison(name), **change))
        widget = CharacterizationStepWidget(study, "Extra-column volume")
        if change is None:
            for box in widget.form._comparison_boxes.values():
                box.value = False
        widget.start_run()
        assert not widget.running and message in widget.status.value

    def test_missing_requirements_block_the_run_and_link_the_earlier_step(
        self, study, navigation, accept_periphery
    ):
        widget = CharacterizationStepWidget(study, "Column packing", on_navigate=navigation)
        widget.form.requires.value = (LENGTH,)
        assert study.steps[1].requires == (LENGTH,)
        (check,) = [c for c in widget.checks if c.id.startswith("requires")]
        assert check.status == "warn"
        widget.start_run()
        assert not widget.running and "Missing requirements" in widget.status.value
        widget.check_buttons()["Open Extra-column volume"].click()
        assert navigation.calls == [("step", {"name": "Extra-column volume"})]

        accept_periphery()
        (check,) = [c for c in widget.checks if c.id.startswith("requires")]
        assert check.status == "ok"

    def test_check_buttons_navigate_to_the_fix(self, study, navigation):
        name = "System pulse 2 (UV)"
        study.replace_comparison(name, replace(study.comparison(name), injection_marker="Nope"))
        widget = CharacterizationStepWidget(study, "Extra-column volume", on_navigate=navigation)
        widget.check_buttons()[f"Open {name}"].click()
        assert navigation.calls == [("measurements", {"select": name})]
        assert f"Open {name}" not in CharacterizationStepWidget(
            study, "Extra-column volume"
        ).check_buttons()

    def test_species_gaps_are_transferred_into_the_prior(self, study, accept_periphery):
        accept_periphery()
        widget = CharacterizationStepWidget(study, "Column packing")
        widget.start_run()
        assert not widget.running and "transfer them first" in widget.status.value

        widget.check_buttons()["Transfer to this step's species"].click()

        prior = study.prior_for("Column packing")
        assert prior is study.posteriors["Extra-column volume"]
        assert prior.value(DISPERSION) == dict.fromkeys(
            ("SystemTracer", "SmallTracer", "LargeTracer"), 4.5e-7
        )
        assert "species_gaps" not in {c.id for c in widget.checks}

    def test_without_an_accepted_step_the_initial_store_takes_the_transfer(self, study):
        study.initial_store = study.initial_store.updated(
            {DISPERSION: {"SystemTracer": 1e-7}},
            Provenance(step="initial", note="assumed"),
        )
        CharacterizationStepWidget(study, "Column packing").transfer_species_gaps()
        assert not study.posteriors
        assert study.prior_for("Column packing").value(DISPERSION)["SmallTracer"] == 1e-7

    def test_assumed_values_are_recorded_on_request(self, study, accept_periphery):
        film = "flow_sheet.column.film_diffusion"
        entry = study.initial_store.entries[film]
        entries = dict(study.initial_store.entries)
        entries[film] = replace(entry, value={"SmallTracer": entry.value["SmallTracer"]})
        study.initial_store = replace(study.initial_store, entries=entries)
        accept_periphery()
        widget = CharacterizationStepWidget(study, "Column packing")
        widget.start_run()
        assert "Record the values the experiment types assume first" in widget.status.value

        widget.check_buttons()["Record the assumptions"].click()

        assert study.prior_for("Column packing").value(film)["LargeTracer"] == 0.0
        assert "assumptions" not in {c.id for c in widget.checks}

    @pytest.mark.parametrize("edited, note", [
        (None, "confirmed default"), (0.75, "known hardware"),
    ])
    def test_a_default_hardware_value_is_confirmed_or_edited(
        self, study, navigation, edited, note
    ):
        store = study.initial_store
        study.initial_store = replace(store, entries={
            k: v for k, v in store.entries.items() if k != DIAMETER
        })
        widget = CharacterizationStepWidget(study, "Extra-column volume", on_navigate=navigation)
        widget.check_buttons()["Edit in System"].click()
        assert navigation.calls == [("system", {"unit": "tubing_pre_column"})]
        assert widget._known_fields[DIAMETER].value == 0.5
        if edited is not None:
            widget._known_fields[DIAMETER].value = edited

        widget.check_buttons()["Use this value"].click()

        entry = study.initial_store.entries[DIAMETER]
        assert entry.value == pytest.approx((edited or 0.5) * 1e-3)
        assert entry.provenance.note == note
        assert "Use this value" not in widget.check_buttons()

    def test_an_unconfirmed_default_does_not_block_the_run(self, study, monkeypatch):
        store = study.initial_store
        study.initial_store = replace(store, entries={
            k: v for k, v in store.entries.items() if k != DIAMETER
        })
        widget = CharacterizationStepWidget(study, "Extra-column volume")
        started = []
        monkeypatch.setattr(threading.Thread, "start", lambda self: started.append(self))
        widget.start_run()
        assert len(started) == 2 and "Fitting Extra-column volume" in widget.status.value


class TestResults:
    def test_candidates_preview_export_and_accept(self, periphery, study, tmp_path):
        result = fake_result(periphery)
        length_before = result.built.processes[0].flow_sheet.tubing_pre_column.length
        show_result(periphery, result)

        assert periphery.candidates[0].tags[0] == AVERAGE_TAG
        assert periphery.results.selected is periphery.candidates[0]
        assert len(periphery.results._charts.children) == 2
        assert result.built.processes[0].flow_sheet.tubing_pre_column.length == length_before
        assert not study.posteriors and periphery.form.name.disabled

        rows = list(csv.reader(periphery.export_candidates_csv(tmp_path / "c.csv").open()))
        assert rows[0] == ["tags", *result.variable_names, *result.objective_names]
        assert len(rows) == 1 + len(periphery.candidates)

        periphery.results.table.value = 1
        periphery.results.btn_accept.click()
        store = study.posteriors["Extra-column volume"]
        assert store.value(LENGTH) == pytest.approx(periphery.candidates[1].x[0])
        assert store.entries[LENGTH].provenance.step == "Extra-column volume"
        assert periphery.accepted and periphery.results.btn_accept.disabled

    def test_edit_setup_discards_an_unaccepted_result_and_applies_deferred_measurements(
        self, periphery, study
    ):
        show_result(periphery, fake_result(periphery))
        study.upsert_comparison(pulse_copy(study, "System pulse 3 (UV)"))
        assert "System pulse 3 (UV)" not in study.steps[0].objective_names

        periphery.edit_setup()

        assert periphery.result is None and not periphery.form.name.disabled
        assert not study.posteriors
        assert "System pulse 3 (UV)" in study.steps[0].objective_names

    def test_removing_a_measurement_elsewhere_discards_the_shown_fit(self, periphery, study):
        show_result(periphery, fake_result(periphery))
        measurements = ComparisonsWidget(study)
        measurements.select("System pulse 2 (UV)")
        measurements._btn_remove.click()
        measurements._btn_remove_confirm.click()
        assert periphery.result is None and not periphery.form.name.disabled
        assert "fit result was discarded" in periphery.status.value


@pytest.mark.parametrize("live", [True, False])
def test_a_stubbed_run_streams_its_front_and_ends_with_candidates(stub_run, live):
    widget, result, spy = stub_run
    length = result.built.processes[0].flow_sheet.tubing_pre_column.length
    widget.live_plot.value = live

    widget.start_run()
    assert widget.running and widget.form.name.disabled
    assert widget.wait(timeout=120)

    assert not widget.running and widget.result is result
    assert widget.candidates and widget.results.selected.tags[0] == AVERAGE_TAG
    assert "Final front: best-average candidate" in widget._live_title.value
    assert "<td>0.42</td><td>m</td>" in widget._best_values.value
    assert result.built.processes[0].flow_sheet.tubing_pre_column.length == length
    assert spy.max_active <= 1
    if live:
        assert 1 <= len(widget.live_update_seconds) < len(GENERATIONS)
        assert spy.live_calls == 2 * len(widget.live_update_seconds)
        assert widget._live_built is not result.built
    else:
        assert spy.live_calls == 0


def test_a_busy_live_update_is_skipped(periphery):
    candidate = Candidate(index=0, x=(0.42, 4.5e-7), f=(0.05, 0.06), tags=(AVERAGE_TAG,))
    periphery._run_setup = periphery.get_value()
    periphery._run_prior = periphery.study.prior_for(periphery.step_name)
    with periphery._live_busy:
        assert not periphery._start_live_update(candidate, 1)
    assert periphery._live_thread is None


@pytest.mark.slow
def test_a_real_run_is_accepted_and_shows_in_the_store(study):
    widget = CharacterizationStepWidget(study, "Extra-column volume")
    view = ParameterStoreWidget(study)
    fields = widget.form._knob_fields["U-NSGA-III"]
    fields[0].value, fields[1].value = 4, 2

    widget.start_run()
    assert widget.wait(timeout=600)
    assert widget.result is not None and widget.result.success, widget.status.value
    assert [s["name"] for s in widget._progress_chart.series] == [
        "System pulse 1 (UV)", "System pulse 2 (UV)",
    ]
    assert all(chart.series for _label, chart in widget._live_chart_widgets)

    widget.accept()

    assert study.current_store.entries[LENGTH].provenance.step == "Extra-column volume"
    row = view._table.rows[view._table.option_labels.index(LENGTH)]
    assert row[4]["text"] == "Extra-column volume"
    assert "System pulse 1 (UV)_NRMSE" in row[7]["text"]
