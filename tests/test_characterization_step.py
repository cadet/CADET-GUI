from __future__ import annotations

import csv
import threading
import time
import warnings
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import ipywidgets as W
import numpy as np
import pytest
from cadetgui.characterization_runner import AVERAGE_TAG, StepResult, build
from cadetgui.parameter_store import Provenance
from cadetgui.study import Study
from cadetgui.widgets.composite import CharacterizationStepWidget, ParameterStoreWidget

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

MANIFEST = (
    Path(__file__).parent.parent / "examples" / "data" / "characterization_akta" / "manifest.json"
)
LENGTH = "flow_sheet.tubing_pre_column.length"
DISPERSION = "flow_sheet.tubing_pre_column.axial_dispersion"


@pytest.fixture
def study() -> Study:
    return Study.load(MANIFEST)


@pytest.fixture
def periphery(study) -> CharacterizationStepWidget:
    return CharacterizationStepWidget(study, "Extra-column volume")


def periphery_posterior(study: Study):
    return study.initial_store.updated(
        {LENGTH: 0.42, DISPERSION: {"SystemTracer": 4.5e-7}},
        Provenance(step="Extra-column volume", probe="SystemTracer"),
    )


class TestSetup:
    def test_shows_the_manifest_step(self, periphery):
        form = periphery.form
        assert form.name.value == "Extra-column volume"
        assert form.stage.value == "tubing"
        assert form._option_fields["tubing"].value == "tubing_pre_column"
        assert form._option_fields["tubing"].option_labels == ["Tubing (pre column)"]
        assert form.selected_names() == ["System pulse 1 (UV)", "System pulse 2 (UV)"]
        lb, ub = form._bound_fields["tubing_pre_column_length"]
        assert (lb.value, ub.value) == (0.1, 1.0)
        assert periphery.get_value().bounds == periphery.study.steps[0].bounds

    def test_constructing_does_not_touch_the_study(self, study):
        before = list(study.steps)
        CharacterizationStepWidget(study, "Extra-column volume")
        assert all(a is b for a, b in zip(study.steps, before))
        assert len(study.steps) == 2

    def test_multi_objective_step_only_offers_u_nsga3(self, periphery):
        form = periphery.form
        assert form.optimizer.option_labels == ["U-NSGA-III"]

        form._comparison_boxes["System pulse 2 (UV)"].value = False
        assert set(form.optimizer.option_labels) == {"Nelder-Mead", "U-NSGA-III"}

    def test_chain_is_a_line_for_template_steps_and_an_editor_for_custom_ones(self, study):
        widget = CharacterizationStepWidget(study, "Column packing")
        form = widget.form
        assert "Uses from earlier steps:" in form._chain_line.value
        assert "Determines:" in form._chain_line.value
        assert form._chain_box not in form._advanced_body.children

    def test_optimizer_settings_are_part_of_the_step(self, study):
        study.steps[0].optimizer = {"name": "U-NSGA-III", "knobs": {"pop_size": 6, "n_max_gen": 3}}
        widget = CharacterizationStepWidget(study, "Extra-column volume")
        form = widget.form
        assert [f.value for f in form._knob_fields["U-NSGA-III"]] == [6, 3]

        form._knob_fields["U-NSGA-III"][1].value = 9
        assert study.steps[0].optimizer == {
            "name": "U-NSGA-III", "knobs": {"pop_size": 6, "n_max_gen": 9}
        }

        form._comparison_boxes["System pulse 2 (UV)"].value = False
        form.optimizer.value = "Nelder-Mead"
        form._knob_fields["Nelder-Mead"][0].value = 25
        assert study.steps[0].optimizer == {"name": "Nelder-Mead", "knobs": {"maxiter": 25}}
        assert widget.get_value().optimizer == study.steps[0].optimizer

    def test_optimizer_knobs_are_sized_and_estimated(self, periphery):
        form = periphery.form
        assert [f.value for f in form._knob_fields["U-NSGA-III"]] == [16, 12]
        assert [f.value for f in form._knob_fields["Nelder-Mead"]] == [400]
        assert "≈ 384 simulations" in form._estimate.value
        assert "0 lets CADET-Process size it" in form._knob_fields["U-NSGA-III"][0].tooltip

        form._knob_fields["U-NSGA-III"][0].value = 0
        assert "CADET-Process sizes the run" in form._estimate.value

    def test_prefill_follows_the_frozen_set_but_keeps_user_edits(self, periphery, study):
        form = periphery.form
        maxiter = form._knob_fields["Nelder-Mead"][0]
        form._fit_boxes["tubing_pre_column_axial_dispersion"].value = False
        assert maxiter.value == 200

        maxiter.value = 300
        form._fit_boxes["tubing_pre_column_axial_dispersion"].value = True
        assert maxiter.value == 300

        pop_size = form._knob_fields["U-NSGA-III"][0]
        pop_size.value = 40
        form.stage.value = "adsorption"
        form._option_fields["is_kinetic"].value = True
        assert [f.value for f in form._knob_fields["U-NSGA-III"]] == [40, 12]
        assert study.steps[0].optimizer == {
            "name": "U-NSGA-III", "knobs": {"pop_size": 40, "n_max_gen": 12}
        }

    def test_loaded_knobs_that_differ_from_the_sizing_count_as_edited(self, study):
        study.steps[0].optimizer = {"name": "U-NSGA-III", "knobs": {"pop_size": 6, "n_max_gen": 12}}
        form = CharacterizationStepWidget(study, "Extra-column volume").form
        form.stage.value = "adsorption"
        form._option_fields["is_kinetic"].value = True
        assert [f.value for f in form._knob_fields["U-NSGA-III"]] == [6, 12]
        assert [f.value for f in form._knob_fields["Nelder-Mead"]] == [600]

    def test_edits_upsert_the_step(self, periphery, study):
        lb, _ = periphery.form._bound_fields["tubing_pre_column_length"]
        lb.value = 0.2
        periphery.form._fit_boxes["tubing_pre_column_axial_dispersion"].value = False

        step = study.steps[0]
        assert step.name == "Extra-column volume"
        assert step.bounds["tubing_pre_column_length"] == (0.2, 1.0)
        assert step.frozen == ("tubing_pre_column_axial_dispersion",)
        assert step.provides == [LENGTH]
        assert len(study.steps) == 2

    def test_rename_keeps_position_and_posterior(self, periphery, study):
        study.accept("Extra-column volume", periphery_posterior(study))
        periphery.form.name.value = "periphery"
        assert [s.name for s in study.steps] == ["periphery", "Column packing"]
        assert set(study.posteriors) == {"periphery"}

    def test_rename_onto_another_step_is_refused(self, periphery, study):
        periphery.form.name.value = "Column packing"
        assert [s.name for s in study.steps] == ["Extra-column volume", "Column packing"]
        assert "already called" in periphery.status.value

    def test_new_step_is_appended_on_first_edit(self, study):
        widget = CharacterizationStepWidget(study)
        assert widget.step_name == "step_3"
        assert len(study.steps) == 2

        widget.form.stage.value = "bed"
        assert [s.name for s in study.steps][-1] == "step_3"
        assert study.steps[-1].stage == "bed"

    def test_stage_options_drive_the_variables(self, study):
        widget = CharacterizationStepWidget(study, "Column packing")
        form = widget.form
        assert "particle_porosity" in form._bound_fields

        form._option_fields["include_particle_porosity"].value = False
        assert "particle_porosity" not in form._bound_fields
        assert study.steps[1].options == {"include_particle_porosity": False}

    def test_component_index_lists_component_names(self, study):
        widget = CharacterizationStepWidget(study, "Column packing")
        widget.form.stage.value = "particles"
        field = widget.form._option_fields["component_index"]
        assert field.option_labels == ["SmallTracer"]
        assert field.value == 0

    def test_tubing_choices_are_units_all_selected_processes_have(self, study):
        widget = CharacterizationStepWidget(study, "Column packing")
        widget.form.stage.value = "tubing"
        assert widget.form._option_fields["tubing"].option_labels == ["Tubing (pre column)"]

        for name in ("Large tracer pulse 1 (UV)", "Large tracer pulse 2 (UV)"):
            widget.form._comparison_boxes[name].value = False
        assert widget.form._option_fields["tubing"].option_labels == [
            "Tubing (pre column)", "Tubing (detectors)",
        ]

    def test_comparison_problems_show_as_a_chip(self, study):
        study.upsert_comparison(replace(study.comparison("System pulse 2 (UV)"), channel="nope"))
        widget = CharacterizationStepWidget(study, "Extra-column volume")
        rows = widget.form._comparison_rows.children
        chips = {row.children[1].value.split("</b>")[0][3:]: row.children[2].value for row in rows}
        assert "cadetgui-msg-ok" in chips["System pulse 1 (UV)"]
        assert "Unknown channel" in chips["System pulse 2 (UV)"]

        widget.start_run()
        assert not widget.running
        assert "Unknown channel" in widget.status.value

    def test_run_needs_a_comparison(self, periphery):
        for box in periphery.form._comparison_boxes.values():
            box.value = False
        periphery.start_run()
        assert not periphery.running
        assert "at least one measurement" in periphery.status.value

    def test_missing_requirements_warn_and_block_the_run(self, study):
        widget = CharacterizationStepWidget(study, "Column packing")
        widget.form.requires.value = (LENGTH,)
        assert study.steps[1].requires == (LENGTH,)
        (check,) = [c for c in widget.checks if c.id.startswith("requires")]
        assert check.status == "warn"
        assert "length (Tubing (pre column))" in check.text
        assert "accept Extra-column volume first" in check.text

        widget.start_run()
        assert not widget.running
        assert "Missing requirements" in widget.status.value

        study.accept("Extra-column volume", periphery_posterior(study))
        (check,) = [c for c in widget.checks if c.id.startswith("requires")]
        assert check.status == "ok"

    def test_follows_step_changes_made_elsewhere(self, periphery, study):
        study.upsert_step(replace(study.steps[0], bounds={"tubing_pre_column_length": (0.3, 0.9)}))
        lb, ub = periphery.form._bound_fields["tubing_pre_column_length"]
        assert (lb.value, ub.value) == (0.3, 0.9)


class TestSpeciesGaps:
    def test_gap_after_the_periphery_step_is_transferred_into_its_posterior(self, study):
        study.accept("Extra-column volume", periphery_posterior(study))
        widget = CharacterizationStepWidget(study, "Column packing")
        assert (
            "Column packing needs axial dispersion (Tubing (pre column)) for SmallTracer, "
            "LargeTracer; Extra-column volume fitted it for SystemTracer" in widget._gaps.value
        )
        assert widget._btn_transfer.layout.display == ""

        widget.start_run()
        assert not widget.running
        assert "transfer them first" in widget.status.value

        widget.transfer_species_gaps()
        prior = study.prior_for("Column packing")
        assert prior is study.posteriors["Extra-column volume"]
        assert prior.value(DISPERSION) == {
            "SystemTracer": 4.5e-7, "SmallTracer": 4.5e-7, "LargeTracer": 4.5e-7,
        }
        assert "transferred" in prior.entries[DISPERSION].provenance.note
        assert widget._gaps.value == ""

    def test_without_an_accepted_step_the_initial_store_is_updated(self, study):
        study.initial_store = study.initial_store.updated(
            {DISPERSION: {"SystemTracer": 1e-7}}, Provenance(step="initial", note="assumed")
        )
        widget = CharacterizationStepWidget(study, "Column packing")
        widget.transfer_species_gaps()
        assert not study.posteriors
        assert study.prior_for("Column packing").value(DISPERSION)["SmallTracer"] == 1e-7


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


def show_result(widget: CharacterizationStepWidget, result: StepResult) -> None:
    widget._run_setup = widget.get_value()
    widget._run_prior = widget.study.prior_for(widget.step_name)
    widget._progress = {"result": result}
    widget.form.set_locked(True)
    widget._finish(time.monotonic())


class TestResults:
    def test_candidates_preview_and_accept(self, periphery, study, tmp_path):
        result = fake_result(periphery)
        length_before = result.built.processes[0].flow_sheet.tubing_pre_column.length
        show_result(periphery, result)

        assert periphery.results.table.columns == [
            "Tags", *result.variable_names,
            "System pulse 1 (UV) (NRMSE)", "System pulse 2 (UV) (NRMSE)",
        ]
        assert periphery.candidates[0].tags[0] == AVERAGE_TAG
        assert periphery.results.selected is periphery.candidates[0]
        assert len(periphery.results._charts.children) == 2
        assert result.built.processes[0].flow_sheet.tubing_pre_column.length == length_before
        assert not study.posteriors
        assert periphery.form.name.disabled
        assert periphery._btn_edit.layout.display == ""

        path = periphery.export_candidates_csv(tmp_path / "candidates.csv")
        rows = list(csv.reader(path.open()))
        assert rows[0] == [
            "tags", *result.variable_names, "System pulse 1 (UV)", "System pulse 2 (UV)",
        ]
        assert len(rows) == 1 + len(periphery.candidates)

        periphery.results.table.value = 1
        periphery.results.btn_accept.click()
        store = study.posteriors["Extra-column volume"]
        chosen = periphery.candidates[1]
        assert store.value(LENGTH) == pytest.approx(chosen.x[0])
        assert store.entries[LENGTH].provenance.step == "Extra-column volume"
        assert periphery.results.btn_accept.disabled

    def test_edit_setup_discards_an_unaccepted_result(self, periphery, study):
        show_result(periphery, fake_result(periphery))
        periphery.edit_setup()
        assert periphery.result is None
        assert not periphery.form.name.disabled
        assert not periphery.running
        assert not study.posteriors


@pytest.mark.slow
def test_runs_accepts_and_the_store_view_shows_the_provenance(study):
    widget = CharacterizationStepWidget(study, "Extra-column volume")
    view = ParameterStoreWidget(study)
    fields = widget.form._knob_fields["U-NSGA-III"]
    fields[0].value, fields[1].value = 4, 2

    widget.start_run()
    assert widget.running
    assert widget.form.name.disabled
    assert widget.wait(timeout=600)

    assert not widget.running
    assert widget.result is not None and widget.result.success, widget.status.value
    assert widget.candidates
    assert widget.results.selected.tags[0] == AVERAGE_TAG
    assert widget._progress_chart.series
    series_names = [s["name"] for s in widget._progress_chart.series]
    assert series_names == ["System pulse 1 (UV)", "System pulse 2 (UV)"]
    assert "Final front: best-average candidate" in widget._live_title.value
    assert all(chart.series for _label, chart in widget._live_chart_widgets)
    assert "tubing_pre_column_length" in widget._best_values.value
    assert not study.posteriors

    widget.accept()

    assert study.current_store.entries[LENGTH].provenance.step == "Extra-column volume"
    labels = view._table.option_labels
    row = view._table.rows[labels.index(LENGTH)]
    assert row[4]["text"] == "Extra-column volume"
    assert "System pulse 1 (UV)_NRMSE" in row[7]["text"]


class TestHeader:
    def test_describes_the_chain_step_open_until_accepted(self, periphery, study):
        from cadetgui.characterization_guide import CHAIN_BY_ID

        guide = CHAIN_BY_ID["system_periphery"]
        header = periphery.header.value

        assert periphery.guide is guide
        assert header.startswith("<details class='cadetgui-info' open>")
        assert "About this step: Extra-column volume" in header
        assert "<ul class='cadetgui-checklist'>" not in header
        assert all(item not in header for item in guide.advice)
        assert "System pulse (no column in line)" in header
        assert "Reading the results" in header
        assert 'data-highlight="true"' in header
        assert 'data-observe="tubing_pre_column"' in header

        study.accept("Extra-column volume", periphery_posterior(study))

        assert periphery.header.value.startswith("<details class='cadetgui-info'>")

    def test_hidden_for_a_step_outside_the_chain(self, study):
        from cadetgui.characterization_runner import StepSetup

        study.upsert_step(
            StepSetup(name="mine", stage="tubing", options={"tubing": "tubing_detectors"})
        )
        widget = CharacterizationStepWidget(study, "mine")

        assert widget.guide is None
        assert widget.header.value == ""
        assert widget._header_box.layout.display == "none"

    def test_labels_carry_glossary_tips(self, periphery):
        import html

        from cadetgui.characterization_guide import GLOSSARY

        texts = " ".join(
            w.value for w in _walk(periphery.root) if isinstance(getattr(w, "value", None), str)
        )
        for term in ("prior", "posterior", "Pareto candidate", "best average", "NRMSE",
                     "fixed variable", "measurement"):
            assert f'data-tip="{html.escape(GLOSSARY[term], quote=True)}"' in texts, term

    def test_old_frozen_term_resolves_to_the_fixed_entry(self):
        from cadetgui.characterization_guide import GLOSSARY
        from cadetgui.widgets._help import term_html

        assert term_html("frozen variable") == term_html("fixed variable", "frozen variable")
        assert "cadetgui-term" in term_html("frozen variable")
        assert "Fit box" in GLOSSARY["fixed variable"]

    def test_species_gap_links_the_glossary(self, study):
        study.accept("Extra-column volume", periphery_posterior(study))
        widget = CharacterizationStepWidget(study, "Column packing")

        assert "(species transfer)</span>" in widget._gaps.value


def _walk(widget):
    yield widget
    for child in getattr(widget, "children", ()):
        yield from _walk(child)


def _texts(widget) -> str:
    return " ".join(
        w.value for w in _walk(widget) if isinstance(getattr(w, "value", None), str)
    )


class TestGuidedSetup:
    def test_chain_step_shows_a_sentence_and_hides_stage_and_options(self, periphery):
        form = periphery.form

        assert form.guided
        assert (
            "Fits the extra-column dead volume and its band broadening, represented as the "
            "length and axial dispersion of the pre-column tubing." in form.summary.value
        )
        assert form._plain_slot.children == ()
        assert form.advanced.layout.display == ""
        assert form.advanced.selected_index is None
        assert form._stage_controls in form._advanced_body.children
        assert form.stage in list(_walk(form.advanced))

    def test_step_type_is_labelled_and_explained_without_stage_wording(self, periphery):
        from cadetgui.characterization_guide import STEP_TYPE_HELP

        form = periphery.form
        assert form.stage.label == "Step type:"
        assert form.advanced.titles[0] == "Advanced: step type and options"
        assert STEP_TYPE_HELP["tubing"] in form._stage_help.value
        form.stage.value = "bed"
        assert STEP_TYPE_HELP["bed"] in form._stage_help.value

    def test_rendered_step_has_no_stage_wording(self, study):
        for name in ("Extra-column volume", "Column packing"):
            root = CharacterizationStepWidget(study, name).root
            parts = []
            for w in _walk(root):
                if isinstance(w, W.HTML) and "<style" not in w.value:
                    parts.append(w.value)
                for attr in ("description", "label"):
                    if isinstance(getattr(w, attr, None), str):
                        parts.append(getattr(w, attr))
                parts += list(getattr(w, "option_labels", ()))
                parts += [str(t) for t in getattr(w, "titles", ()) or ()]
            text = " ".join(parts).lower()
            assert "stage" not in text and "fit step" not in text

    def test_advanced_options_have_readable_labels_and_help(self, periphery):
        form = periphery.form
        tubing = form._option_fields["tubing"]

        assert tubing.label == "Tubing segment:"
        assert tubing.option_labels == ["Tubing (pre column)"]
        help_text = _texts(form._options_box)
        assert "stands in for the whole extra-column volume" in help_text

    def test_custom_step_shows_the_controls_with_labels_and_help(self, study):
        from cadetgui.characterization_runner import StepSetup

        study.upsert_step(StepSetup(name="my own fit", stage="bed"))
        form = CharacterizationStepWidget(study, "my own fit").form

        assert not form.guided
        assert form._stage_controls in form._plain_slot.children
        assert form._advanced_body.children == (form._chain_box,)
        assert form.advanced.get_title(0) == "Advanced: chain links"
        assert form._chain_line.value == ""
        assert ("bed porosity (Column)", "flow_sheet.column.bed_porosity") in form.requires.options
        assert form._option_fields["include_particle_porosity"].label == "Fit particle porosity"
        assert "small tracer that enters the pores" in _texts(form._options_box)
        assert "Fits how the column is packed" in form.summary.value

    def test_leaving_the_chain_options_keeps_a_named_step_guided(self, periphery):
        periphery.form.stage.value = "bed"
        assert periphery.form.guided
        assert "Fits how the column is packed" in periphery.form.summary.value


class TestCurrentValues:
    def test_values_come_from_the_process_setup_with_units(self, periphery):
        cells = periphery.form._current_cells

        assert cells["tubing_pre_column_length"].value == (
            "0.1 m<br><small>from the process setup</small>"
        )
        assert "m<sup>2</sup><sub>IV</sub>/s" in cells["tubing_pre_column_axial_dispersion"].value

    def test_a_later_step_starts_from_the_accepted_value(self, study):
        from cadetgui.characterization_runner import StepSetup

        pulses = [c for c in study.comparisons if c.experiment_type == "system_pulse"]
        study.upsert_step(StepSetup(
            name="Refit tubing", stage="tubing", options={"tubing": "tubing_pre_column"},
            comparisons=pulses,
        ))
        widget = CharacterizationStepWidget(study, "Refit tubing")
        cell = widget.form._current_cells["tubing_pre_column_length"]
        assert "from the process setup" in cell.value

        study.accept("Extra-column volume", periphery_posterior(study))

        assert cell.value == "0.42 m<br><small>from Extra-column volume</small>"
        dispersion = widget.form._current_cells["tubing_pre_column_axial_dispersion"].value
        assert dispersion.startswith("4.5e-07 ")

    def test_species_values_are_shown_per_component_with_their_source(self, study):
        from cadetgui.characterization_guide import (
            ASSUMED_BY_TYPE,
            EXPERIMENT_TYPES,
            STARTING_VALUE,
            starting_values,
            with_implied_values,
        )
        from cadetgui.characterization_runner import StepSetup

        tracers = study.steps[1].comparisons
        setup = StepSetup(
            name="Tracer transport", stage="particles",
            options={"include_film_diffusion": True}, comparisons=tracers,
        )
        values = starting_values(study, setup)
        film = values["film_diffusion"]
        assert film.source == STARTING_VALUE
        assert film.text == "SmallTracer: 8e-05; LargeTracer: 0"
        assert film.unit == r"\frac{\mathrm{m}}{\mathrm{s}}"

        large = [c for c in tracers if c.probe == "LargeTracer"]
        study.initial_store = with_implied_values(
            study.initial_store, EXPERIMENT_TYPES["column_pulse_large_tracer"], "LargeTracer"
        )
        values = starting_values(study, StepSetup(
            name="Large only", stage="particles",
            options={"include_film_diffusion": True}, comparisons=large,
        ))
        assert values["film_diffusion"].text == "0"
        assert values["film_diffusion"].source == ASSUMED_BY_TYPE


class TestFitCheckbox:
    def test_unticking_fit_fixes_the_variable(self, periphery, study):
        box = periphery.form._fit_boxes["tubing_pre_column_axial_dispersion"]
        assert box.value and box.description == "Fit"

        box.value = False
        assert study.steps[0].frozen == ("tubing_pre_column_axial_dispersion",)
        box.value = True
        assert study.steps[0].frozen == ()

    def test_a_loaded_frozen_variable_shows_unticked(self, study):
        study.steps[0].frozen = ("tubing_pre_column_length",)
        form = CharacterizationStepWidget(study, "Extra-column volume").form
        assert not form._fit_boxes["tubing_pre_column_length"].value
        assert form._fit_boxes["tubing_pre_column_axial_dispersion"].value
        assert "fixed" in _texts(form._variables_box)
        assert "Frozen" not in _texts(form._variables_box)


class Navigation:
    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, target, context) -> None:
        self.calls.append((target, dict(context)))


def pulse_copy(study: Study, name: str, source: str = "System pulse 1 (UV)"):
    return replace(study.comparison(source), name=name)


class TestMeasurementSelection:
    def test_a_chain_step_lists_only_measurements_that_feed_it(self, periphery):
        assert list(periphery.form._comparison_boxes) == [
            "System pulse 1 (UV)", "System pulse 2 (UV)",
        ]
        assert "untick one to leave it out" in periphery.form._comparison_note.value

    def test_exclusion_persists_and_new_fitting_measurements_are_included(self, study):
        widget = CharacterizationStepWidget(study, "Extra-column volume")
        widget.form._comparison_boxes["System pulse 2 (UV)"].value = False
        assert study.steps[0].objective_names == ["System pulse 1 (UV)"]

        study.upsert_comparison(pulse_copy(study, "System pulse 3 (UV)"))
        study.upsert_comparison(pulse_copy(study, "Small 3", "Small tracer pulse 1 (conductivity)"))

        assert study.steps[0].objective_names == ["System pulse 1 (UV)", "System pulse 3 (UV)"]
        boxes = widget.form._comparison_boxes
        assert list(boxes) == [
            "System pulse 1 (UV)", "System pulse 2 (UV)", "System pulse 3 (UV)",
        ]
        assert not boxes["System pulse 2 (UV)"].value
        packing = study.steps[1].objective_names
        assert "Small 3" not in packing

    def test_a_widget_constructed_later_keeps_the_exclusion(self, study):
        study.upsert_step(replace(study.steps[0], comparisons=study.steps[0].comparisons[:1]))
        widget = CharacterizationStepWidget(study, "Extra-column volume")
        assert not widget.form._comparison_boxes["System pulse 2 (UV)"].value
        study.notify()
        assert study.steps[0].objective_names == ["System pulse 1 (UV)"]

    def test_an_unticked_measurement_is_saved_with_the_study(self, study, tmp_path):
        widget = CharacterizationStepWidget(study, "Extra-column volume")
        widget.form._comparison_boxes["System pulse 2 (UV)"].value = False
        assert study.steps[0].excluded == ("System pulse 2 (UV)",)

        reloaded = Study.load(study.save(tmp_path / "study.json"))
        reopened = CharacterizationStepWidget(reloaded, "Extra-column volume")
        boxes = reopened.form._comparison_boxes
        assert {n: b.value for n, b in boxes.items()} == {
            "System pulse 1 (UV)": True, "System pulse 2 (UV)": False,
        }

        reloaded.upsert_comparison(pulse_copy(reloaded, "System pulse 3 (UV)"))
        assert reloaded.steps[0].objective_names == ["System pulse 1 (UV)", "System pulse 3 (UV)"]

        reopened.form._comparison_boxes["System pulse 2 (UV)"].value = True
        assert reloaded.steps[0].excluded == ()

    def test_only_recorded_exclusions_are_kept_from_a_loaded_step(self, study):
        step = study.steps[0]
        study.upsert_step(replace(step, comparisons=step.comparisons[:1], excluded=()))
        widget = CharacterizationStepWidget(study, "Extra-column volume")
        assert not widget.form._comparison_boxes["System pulse 2 (UV)"].value
        study.notify()
        assert study.steps[0].objective_names == ["System pulse 1 (UV)", "System pulse 2 (UV)"]

    def test_a_custom_step_lists_every_measurement_and_includes_none_automatically(self, study):
        from cadetgui.characterization_runner import StepSetup

        study.upsert_step(
            StepSetup(name="mine", stage="bed", options={"include_particle_porosity": False})
        )
        widget = CharacterizationStepWidget(study, "mine")
        assert list(widget.form._comparison_boxes) == [c.name for c in study.comparisons]
        assert widget.form._comparison_note.value == ""

        study.upsert_comparison(pulse_copy(study, "System pulse 3 (UV)"))
        assert "System pulse 3 (UV)" in widget.form._comparison_boxes
        assert study.steps[-1].comparisons == []

    def test_a_member_that_does_not_fit_is_warned_and_can_be_removed(self, study):
        legacy = [*study.steps[0].comparisons, study.comparison("Large tracer pulse 1 (UV)")]
        study.upsert_step(replace(study.steps[0], comparisons=legacy))
        widget = CharacterizationStepWidget(study, "Extra-column volume")

        rows = {row.children[0]: row for row in widget.form._comparison_rows.children}
        box = widget.form._comparison_boxes["Large tracer pulse 1 (UV)"]
        warning = rows[box].children[3].value
        assert box.value
        assert "Does not fit this step" in warning
        assert "Column pulse, large tracer (UV) feeds Column packing" in warning

        box.value = False
        assert "Large tracer pulse 1 (UV)" not in study.steps[0].objective_names
        widget.form.refresh_comparisons()
        assert "Large tracer pulse 1 (UV)" not in widget.form._comparison_boxes

    def test_no_fitting_measurement_offers_to_add_one(self, study):
        from cadetgui.characterization_guide import CHAIN_BY_ID, new_step_setup

        study.upsert_step(new_step_setup(CHAIN_BY_ID["particle_transport"], []))
        navigate = Navigation()
        widget = CharacterizationStepWidget(study, "Particle transport", on_navigate=navigate)
        form = widget.form

        assert form._comparison_boxes == {}
        assert "No measurement fits this step yet" in form._no_fitting.value
        assert "Non-binding protein pulse" in form._no_fitting.value
        assert form._btn_add_measurement.layout.display == ""
        form._btn_add_measurement.click()
        assert navigate.calls == [("measurements", {"step_id": "particle_transport"})]

        standalone = CharacterizationStepWidget(study, "Particle transport")
        assert standalone.form._btn_add_measurement.layout.display == "none"

    def test_a_result_on_screen_defers_new_measurements_until_edit(self, periphery, study):
        show_result(periphery, fake_result(periphery))
        study.upsert_comparison(pulse_copy(study, "System pulse 3 (UV)"))
        assert "System pulse 3 (UV)" not in study.steps[0].objective_names

        periphery.edit_setup()
        assert "System pulse 3 (UV)" in study.steps[0].objective_names


def checks_by_id(widget) -> dict:
    return {c.id: c for c in widget.checks}


class TestLiveChecks:
    def test_the_example_step_passes(self, periphery):
        checks = checks_by_id(periphery)
        assert checks["measurements"].status == "ok"
        assert checks["measurements"].text == "2 measurements attached (replicates)."
        assert checks["markers"].status == "ok"
        assert "Injection marker found in every measurement (2)" in checks["markers"].text
        assert checks["problems"].status == "ok"
        known = checks["known:flow_sheet.tubing_pre_column.diameter"]
        assert known.status == "ok" and "the parameter store" in known.text
        assert "Before you run" in _texts(periphery.root)
        assert "cadetgui-msg-ok" in _texts(periphery._checks_box)

    def test_a_single_measurement_asks_for_a_replicate(self, study):
        navigate = Navigation()
        widget = CharacterizationStepWidget(study, "Extra-column volume", on_navigate=navigate)
        widget.form._comparison_boxes["System pulse 2 (UV)"].value = False
        check = checks_by_id(widget)["measurements"]
        assert check.status == "info" and "replicate" in check.text
        widget.check_buttons()["Add a replicate"].click()
        assert navigate.calls == [("measurements", {"step_id": "system_periphery"})]

    def test_a_broken_measurement_links_to_it(self, study):
        study.upsert_comparison(replace(
            study.comparison("System pulse 2 (UV)"), injection_marker="Phase Nope",
        ))
        study.upsert_comparison(replace(
            study.comparison("System pulse 1 (UV)"), baseline_window=(1e6, 2e6),
        ))
        navigate = Navigation()
        widget = CharacterizationStepWidget(study, "Extra-column volume", on_navigate=navigate)
        checks = checks_by_id(widget)

        marker = checks["marker:System pulse 2 (UV)"]
        assert marker.status == "warn"
        assert "'Phase Nope' not found in the run log" in marker.text
        assert "problems:System pulse 2 (UV)" not in checks
        baseline = checks["problems:System pulse 1 (UV)"]
        assert "No points in the baseline fitting window" in baseline.text

        buttons = widget.check_buttons()
        buttons["Open System pulse 2 (UV)"].click()
        buttons["Open System pulse 1 (UV)"].click()
        assert navigate.calls == [
            ("measurements", {"select": "System pulse 2 (UV)"}),
            ("measurements", {"select": "System pulse 1 (UV)"}),
        ]
        assert "Open System pulse 2 (UV)" not in CharacterizationStepWidget(
            study, "Extra-column volume"
        ).check_buttons()

    def test_missing_requirement_links_the_earlier_step(self, study):
        navigate = Navigation()
        widget = CharacterizationStepWidget(study, "Column packing", on_navigate=navigate)
        widget.check_buttons()["Open Extra-column volume"].click()
        assert navigate.calls == [("step", {"name": "Extra-column volume"})]

    def test_species_gap_offers_the_transfer(self, study):
        study.accept("Extra-column volume", periphery_posterior(study))
        widget = CharacterizationStepWidget(study, "Column packing")
        assert checks_by_id(widget)["species_gaps"].status == "warn"
        assert widget._btn_transfer in list(_walk(widget._checks_box))

        widget.check_buttons()["Transfer to this step's species"].click()
        assert "species_gaps" not in checks_by_id(widget)
        assert study.prior_for("Column packing").value(DISPERSION)["LargeTracer"] == 4.5e-7

    def test_a_missing_assumption_is_recorded_explicitly(self, study):
        from cadetgui.step_checks import study_steps_status

        film = "flow_sheet.column.film_diffusion"
        entry = study.initial_store.entries[film]
        entries = dict(study.initial_store.entries)
        entries[film] = replace(entry, value={"SmallTracer": entry.value["SmallTracer"]})
        study.initial_store = replace(study.initial_store, entries=entries)
        study.accept("Extra-column volume", periphery_posterior(study))
        widget = CharacterizationStepWidget(study, "Column packing")

        status = study_steps_status(study)[1]
        assert status.next_action.startswith("The experiment types assume values")
        assert all("film_diffusion" not in path for path in status.species_gaps)

        check = checks_by_id(widget)["assumptions"]
        assert "film diffusion (Column) = 0 for LargeTracer" in check.text
        assert "film diffusion" not in checks_by_id(widget)["species_gaps"].text
        widget.start_run()
        assert "Record the values the experiment types assume first" in widget.status.value

        widget.transfer_species_gaps()
        assert "LargeTracer" not in study.prior_for("Column packing").value(film)
        widget.check_buttons()["Record the assumptions"].click()
        prior = study.prior_for("Column packing")
        assert prior.value(film)["LargeTracer"] == 0.0
        assert "assumed" in prior.entries[film].provenance.step
        assert "assumptions" not in checks_by_id(widget)

    @staticmethod
    def _without_pre_column_diameter(study):
        from cadetgui.parameter_store import ParameterStore

        store = study.initial_store
        study.initial_store = ParameterStore(
            specs=store.specs,
            entries={
                k: v for k, v in store.entries.items() if not k.endswith("pre_column.diameter")
            },
            step=store.step,
        )

    def test_a_default_hardware_value_is_a_note_with_its_value_and_two_actions(self, study):
        self._without_pre_column_diameter(study)
        navigate = Navigation()
        widget = CharacterizationStepWidget(study, "Extra-column volume", on_navigate=navigate)
        check = checks_by_id(widget)["known:flow_sheet.tubing_pre_column.diameter"]

        assert check.status == "info"
        assert check.text == (
            "Pre-column tubing diameter: using the default 0.5 mm. Is that your hardware?"
        )
        assert "not set" not in check.text
        buttons = widget.check_buttons()
        assert {"Use this value", "Edit in System"} <= set(buttons)
        assert widget._known_fields["flow_sheet.tubing_pre_column.diameter"].value == 0.5

        buttons["Edit in System"].click()
        assert navigate.calls == [("system", {"unit": "tubing_pre_column"})]
        assert "Before you run" in _texts(widget.root)
        standalone = CharacterizationStepWidget(study, "Extra-column volume").check_buttons()
        assert "Use this value" in standalone and "Edit in System" not in standalone

    def test_an_unconfirmed_default_does_not_block_the_run(self, study, monkeypatch):
        self._without_pre_column_diameter(study)
        widget = CharacterizationStepWidget(study, "Extra-column volume")
        started = []
        monkeypatch.setattr(threading.Thread, "start", lambda self: started.append(self))
        widget.start_run()
        assert len(started) == 2 and "Fitting Extra-column volume" in widget.status.value

    def test_use_this_value_records_the_confirmed_default(self, study):
        self._without_pre_column_diameter(study)
        study.accept("Extra-column volume", periphery_posterior(study))
        widget = CharacterizationStepWidget(study, "Extra-column volume")
        path = "flow_sheet.tubing_pre_column.diameter"

        widget.check_buttons()["Use this value"].click()

        entry = study.initial_store.entries[path]
        assert entry.value == pytest.approx(0.5e-3)
        assert entry.provenance.step == "initial"
        assert entry.provenance.note == "confirmed default"
        assert entry.provenance.source == "known hardware"
        assert study.initial_store.step == "initial"
        assert study.posteriors["Extra-column volume"].entries[path].value == pytest.approx(5e-4)
        check = checks_by_id(widget)[f"known:{path}"]
        assert check.status == "ok"
        assert check.text == (
            "Pre-column tubing diameter: 0.5 mm (confirmed default, in the parameter store)."
        )
        assert "Use this value" not in widget.check_buttons()
        assert "known hardware" in widget.status.value

    def test_an_edited_value_is_recorded_as_known_hardware(self, study):
        self._without_pre_column_diameter(study)
        widget = CharacterizationStepWidget(study, "Extra-column volume")
        path = "flow_sheet.tubing_pre_column.diameter"

        widget._known_fields[path].value = 0.75
        widget.check_buttons()["Use this value"].click()

        entry = study.initial_store.entries[path]
        assert entry.value == pytest.approx(0.75e-3)
        assert entry.provenance.note == "known hardware"
        check = checks_by_id(widget)[f"known:{path}"]
        assert check.status == "ok" and "0.75 mm" in check.text

    def test_advice_moves_into_the_help(self, periphery):
        from cadetgui.characterization_guide import CHAIN_BY_ID

        header = periphery.header.value
        assert "Also check" not in header and "are in the Guide" in header
        assert "baseline window is set" not in header
        assert all("marker" not in item for item in CHAIN_BY_ID["system_periphery"].advice)

    def test_the_workbench_wires_navigation_and_selects_measurements(self, study):
        from cadetgui.widgets.composite import CharacterizationWorkbenchWidget

        workbench = CharacterizationWorkbenchWidget(study=study)
        step = workbench.steps["Extra-column volume"]
        assert step.on_navigate == workbench.navigate

        workbench.navigate("measurements", {"select": "System pulse 2 (UV)"})
        assert workbench.comparisons.selected.name == "System pulse 2 (UV)"


class FakeOptimizer:
    """Mimics the part of a running optimizer the progress ticker reads."""

    def __init__(self) -> None:
        self.results = SimpleNamespace(populations=[], pareto_fronts=[], meta_front=None)

    def add_generation(self, x, f) -> None:
        f = np.asarray(f, dtype=float)
        self.results.populations.append(SimpleNamespace(f_min=f.min(axis=0)))
        front = SimpleNamespace(x_independent=np.asarray(x, dtype=float), f=f)
        self.results.pareto_fronts.append(front)
        self.results.meta_front = front


def fake_run(widget, generations, delay):
    """Return a stand-in for `characterization_runner.run` that yields `generations`."""
    result = fake_result(widget)

    def run(setup, store, *, on_optimizer_ready, cancel_event, **_kwargs):
        optimizer = FakeOptimizer()
        on_optimizer_ready(optimizer)
        for x, f in generations:
            time.sleep(delay)
            optimizer.add_generation(x, f)
            if cancel_event.is_set():
                break
        time.sleep(delay)
        return result

    return run, result


class TestLiveFitPlot:
    GENERATIONS = [
        ([[0.3, 1e-7], [0.6, 2e-6]], [[0.4, 0.5], [0.3, 0.2]]),
        ([[0.42, 4.5e-7], [0.6, 2e-6]], [[0.05, 0.06], [0.3, 0.2]]),
        ([[0.42, 4.5e-7], [0.41, 4e-7]], [[0.05, 0.06], [0.04, 0.05]]),
        ([[0.42, 4.5e-7], [0.41, 4e-7]], [[0.05, 0.06], [0.04, 0.05]]),
    ]

    @pytest.fixture
    def spied(self, monkeypatch, periphery):
        from cadetgui import characterization_runner
        from cadetgui.comparison import Comparison

        run, result = fake_run(periphery, self.GENERATIONS, delay=0.15)
        monkeypatch.setattr(characterization_runner, "run", run)
        periphery._TICK_SECONDS = 0.02

        spy = SimpleNamespace(active=0, max_active=0, live_calls=0, built=[], lock=threading.Lock())
        evaluate, posterior = Comparison.evaluate, characterization_runner.posterior

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

        def spy_posterior(setup, built, store, candidate):
            spy.built.append(built)
            return posterior(setup, built, store, candidate)

        monkeypatch.setattr(Comparison, "evaluate", slow_evaluate)
        monkeypatch.setattr(characterization_runner, "posterior", spy_posterior)
        return periphery, result, spy

    def test_updates_from_the_run_without_touching_its_processes(self, spied):
        widget, result, spy = spied
        length = result.built.processes[0].flow_sheet.tubing_pre_column.length

        widget.start_run()
        assert widget.live_plot.value
        assert len(widget._live_chart_widgets) == 2
        assert widget.wait(timeout=120)

        assert widget.live_update_seconds
        assert spy.live_calls == 2 * len(widget.live_update_seconds)
        assert spy.max_active == 1
        assert all(built is not result.built for built in spy.built)
        assert result.built.processes[0].flow_sheet.tubing_pre_column.length == length
        assert widget._live_built is not result.built

        assert "Final front: best-average candidate" in widget._live_title.value
        for label, chart in widget._live_chart_widgets:
            assert "NRMSE" in label.value
            assert [s["name"] for s in chart.series] == ["Simulated", "Measured"]

    def test_updates_never_overlap(self, spied):
        widget, _result, spy = spied
        widget.start_run()
        assert widget.wait(timeout=120)
        assert spy.max_active == 1
        assert 1 <= len(widget.live_update_seconds) < len(self.GENERATIONS)

    def test_a_busy_update_is_skipped(self, periphery):
        from cadetgui.characterization_runner import Candidate

        candidate = Candidate(index=0, x=(0.42, 4.5e-7), f=(0.05, 0.06), tags=("best average",))
        periphery._run_setup = periphery.get_value()
        periphery._run_prior = periphery.study.prior_for(periphery.step_name)
        periphery._live_busy.acquire()
        try:
            assert not periphery._start_live_update(candidate, 1)
        finally:
            periphery._live_busy.release()
        assert periphery._live_thread is None

    def test_can_be_switched_off(self, spied):
        widget, _result, spy = spied
        widget.live_plot.value = False
        widget.start_run()
        assert widget.wait(timeout=120)
        assert spy.live_calls == 0
        assert "Final front" in widget._live_title.value

    def test_best_values_show_in_the_results_after_the_run_only(self, spied):
        widget, _result, _spy = spied
        seen = []
        widget._best_values.observe(lambda c: seen.append((widget.running, c["new"])), "value")
        widget.start_run()
        assert widget.wait(timeout=120)
        assert all(not value for running, value in seen if running)
        assert widget._best_values not in list(_walk(widget._progress_box))
        table = widget._best_values.value
        assert "Best average</span> of the final front" in table
        assert "tubing_pre_column_length" in table
        assert "<td>0.42</td><td>m</td>" in table
        assert "tubing_pre_column_axial_dispersion" in table
        assert "<td>System pulse 1 (UV)</td><td>0.05</td>" in table

    def test_variable_names_match_the_problem(self, study):
        from cadetgui.characterization_runner import fitted_variables
        from cadetgui.characterization_stages import describe_stage

        for setup in study.steps:
            built = build(setup, study.initial_store.updated(
                {LENGTH: 0.4, DISPERSION: {"SystemTracer": 1e-7, "SmallTracer": 1e-7,
                                           "LargeTracer": 1e-7}},
                Provenance(step="test"),
            ))
            names = fitted_variables(describe_stage(setup.stage, **setup.options), setup.frozen)
            assert names == list(built.problem.independent_variable_names)


def test_posterior_reads_each_probe_from_its_own_process(study):
    from cadetgui.characterization_runner import Candidate, posterior

    prior = periphery_posterior(study).updated(
        {DISPERSION: {"SmallTracer": 4.5e-7, "LargeTracer": 4.5e-7}}, Provenance(step="t")
    )
    setup = study.steps[1]
    built = build(setup, prior)
    problem = built.problem
    x = tuple(
        (lb + ub) / 2
        for lb, ub in zip(problem.lower_bounds_independent, problem.upper_bounds_independent)
    )
    store = posterior(setup, built, prior, Candidate(0, x, (0.0,) * 4, ("best average",)))
    assert set(store.value("flow_sheet.column.axial_dispersion")) == {"SmallTracer", "LargeTracer"}


def test_hardware_values_read_in_lab_units():
    from cadetgui.step_checks import known_value_label, quantity_text

    assert quantity_text(0.5e-3, r"\mathrm{m}") == ("0.5 mm", 1e-3, "mm")
    assert quantity_text(5e-6, r"\mathrm{m}")[0] == "5 µm"
    assert quantity_text(1.2, r"\frac{\mathrm{mol}}{\mathrm{m}^{3}}")[0] == "1.2 mol/m³"
    assert known_value_label("flow_sheet.tubing_pre_column.diameter") == (
        "Pre-column tubing diameter"
    )
    assert known_value_label("flow_sheet.column.length") == "Column length"
    assert known_value_label("flow_sheet.column.binding_model.capacity") == "Ionic capacity"


def test_removing_a_measurement_from_measurements_discards_the_shown_fit(periphery, study):
    from cadetgui.widgets.composite import ComparisonsWidget

    show_result(periphery, fake_result(periphery))
    assert periphery._lock_note.layout.display == ""
    measurements = ComparisonsWidget(study)
    measurements.select("System pulse 2 (UV)")

    measurements._btn_remove.click()
    assert measurements._remove_confirm.layout.display == ""
    assert "Extra-column volume" in measurements._remove_note.value
    assert "System pulse 2 (UV)" in [c.name for c in study.comparisons]

    measurements._btn_remove_confirm.click()
    assert "System pulse 2 (UV)" not in [c.name for c in study.comparisons]
    assert [c.name for c in study.steps[0].comparisons] == ["System pulse 1 (UV)"]
    assert periphery.result is None
    assert not periphery.form.name.disabled
    assert "fit result was discarded" in periphery.status.value
