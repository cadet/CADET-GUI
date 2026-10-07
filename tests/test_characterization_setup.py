from __future__ import annotations

import warnings
from pathlib import Path

import pytest
from cadetgui.characterization_guide import DEFAULT_CHAIN
from cadetgui.characterization_runner import StepSetup
from cadetgui.parameter_store import Provenance
from cadetgui.study import Study
from cadetgui.widgets.composite.characterization_setup import (
    ADD_ANOTHER,
    ADD_MEASUREMENT,
    OPEN_STEP,
    TRANSFER,
    CharacterizationSetupWidget,
    runs_use_text,
    set_up_label,
    step_diagrams_html,
)

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

MANIFEST = (
    Path(__file__).parent.parent / "examples" / "data" / "characterization_akta" / "manifest.json"
)
LENGTH = "flow_sheet.tubing_pre_column.length"
DISPERSION = "flow_sheet.tubing_pre_column.axial_dispersion"
DIAGRAM = 'aria-label="Flow path of the LC system"'


class Spy:
    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, target: str, context: dict) -> None:
        self.calls.append((target, context))


@pytest.fixture
def study() -> Study:
    return Study.load(MANIFEST)


def _labels(setup_pane):
    return {key: button.description for key, button in setup_pane.buttons.items()}


def _card_text(setup_pane, index: int) -> str:
    def walk(widget):
        yield widget
        for child in getattr(widget, "children", ()):
            yield from walk(child)

    return " ".join(
        w.value for w in walk(setup_pane._cards.children[index])
        if isinstance(getattr(w, "value", None), str)
    )


def test_one_card_per_chain_step_in_lab_order(study):
    setup_pane = CharacterizationSetupWidget(study)

    assert len(setup_pane._cards.children) == len(DEFAULT_CHAIN)
    assert list(setup_pane.buttons) == [g.id for g in DEFAULT_CHAIN]
    for index, guide in enumerate(DEFAULT_CHAIN):
        text = _card_text(setup_pane, index)
        assert f"{index + 1}. {guide.title}" in text
        assert 'data-highlight="true"' in text
    assert "<th>Measurements</th>" in _card_text(setup_pane, 0)
    assert "<td>System pulse 1 (UV), System pulse 2 (UV)</td>" in _card_text(setup_pane, 0)
    assert "not started" in _card_text(setup_pane, 2)


def test_status_before_and_after_accepting_the_first_step(study):
    setup_pane = CharacterizationSetupWidget(study)

    assert setup_pane.statuses["Extra-column volume"].ready
    assert _labels(setup_pane) == {
        "system_periphery": OPEN_STEP,
        "column_packing": OPEN_STEP,
        "particle_transport": ADD_MEASUREMENT,
        "binding": ADD_MEASUREMENT,
        "capacity": ADD_MEASUREMENT,
    }
    assert "accept Extra-column volume first." in _card_text(setup_pane, 1)

    study.accept("Extra-column volume", study.initial_store.updated(
        {LENGTH: 0.42, DISPERSION: {"SystemTracer": 4.5e-7}},
        Provenance(step="Extra-column volume", probe="SystemTracer"),
    ))

    assert setup_pane.statuses["Extra-column volume"].accepted
    assert "accepted" in _card_text(setup_pane, 0)
    assert _labels(setup_pane)["column_packing"] == TRANSFER
    assert "Carry them over explicitly" in _card_text(setup_pane, 1)


def test_fitted_steps_are_shown_as_waiting_for_a_choice(study):
    fitted: set = set()
    setup_pane = CharacterizationSetupWidget(study, fitted_steps=lambda: fitted)

    fitted.add("Extra-column volume")
    setup_pane.refresh()

    assert setup_pane.statuses["Extra-column volume"].fitted
    assert "fitted, choose a candidate" in _card_text(setup_pane, 0)


def test_open_step_and_transfer_navigate_to_the_step(study):
    spy = Spy()
    setup_pane = CharacterizationSetupWidget(study, on_navigate=spy)

    setup_pane.buttons["column_packing"].click()

    assert spy.calls == [("step", {"name": "Column packing"})]


def _protein_pulse(study, name="Protein pulse 1"):
    import dataclasses

    large = study.comparison("Large tracer pulse 1 (UV)")
    return dataclasses.replace(large, name=name, experiment_type="nonbinding_protein_pulse")


def test_a_step_without_measurements_only_offers_adding_one(study):
    spy = Spy()
    setup_pane = CharacterizationSetupWidget(study, on_navigate=spy)

    assert setup_pane.buttons["particle_transport"].description == ADD_MEASUREMENT
    assert "particle_transport" not in setup_pane.secondary_buttons
    assert "Add a measurement for this step first" in _card_text(setup_pane, 2)
    setup_pane.buttons["particle_transport"].click()
    assert spy.calls == [("measurements", {"step_id": "particle_transport"})]


def test_a_step_with_measurements_offers_set_up_and_another_measurement(study):
    spy = Spy()
    setup_pane = CharacterizationSetupWidget(study, on_navigate=spy)
    study.upsert_comparison(_protein_pulse(study))

    assert setup_pane.buttons["particle_transport"].description == set_up_label(1)
    assert set_up_label(2) == "Set up this step (2 measurements)"
    assert setup_pane.buttons["particle_transport"].button_style == "primary"
    secondary = setup_pane.secondary_buttons["particle_transport"]
    assert secondary.description == ADD_ANOTHER
    assert secondary.button_style == ""
    secondary.click()
    assert spy.calls == [("measurements", {"step_id": "particle_transport"})]


def test_set_up_this_step_upserts_the_step_with_tagged_measurements(study):
    spy = Spy()
    upserted = []
    upsert = study.upsert_step
    study.upsert_step = lambda step: (upserted.append(step), upsert(step))
    setup_pane = CharacterizationSetupWidget(study, on_navigate=spy)
    study.upsert_comparison(_protein_pulse(study))

    setup_pane.buttons["particle_transport"].click()

    assert [s.name for s in upserted] == ["Particle transport"]
    assert study.steps[-1].stage == "particles"
    assert [c.name for c in study.steps[-1].comparisons] == ["Protein pulse 1"]
    assert spy.calls == [("step", {"name": "Particle transport"})]
    assert "not started" not in _card_text(setup_pane, 2)
    assert setup_pane.statuses["Particle transport"].guide.id == "particle_transport"


def test_set_up_keeps_chain_order():
    study = Study()
    setup_pane = CharacterizationSetupWidget(study)

    setup_pane.set_up("binding")
    setup_pane.set_up("system_periphery")

    assert [s.name for s in study.steps] == ["Extra-column volume", "Binding"]


def test_add_measurement_navigates_with_the_step():
    study = Study()
    study.upsert_step(StepSetup(name="system_periphery", stage="tubing"))
    spy = Spy()
    setup_pane = CharacterizationSetupWidget(study, on_navigate=spy)

    assert setup_pane.buttons["system_periphery"].description == ADD_MEASUREMENT
    setup_pane.buttons["system_periphery"].click()

    assert spy.calls == [("measurements", {"step_id": "system_periphery"})]


def test_custom_steps_get_their_own_card():
    study = Study()
    study.upsert_step(
        StepSetup(name="mine", stage="tubing", options={"tubing": "tubing_detectors"})
    )
    setup_pane = CharacterizationSetupWidget(study)

    assert len(setup_pane._cards.children) == len(DEFAULT_CHAIN) + 1
    assert setup_pane.buttons["mine"].description == OPEN_STEP


def test_manual_refresh_only_when_auto_refresh_is_off(study):
    setup_pane = CharacterizationSetupWidget(study, auto_refresh=False)

    study.accept("Extra-column volume", study.initial_store)

    assert setup_pane.stale
    assert not setup_pane.statuses["Extra-column volume"].accepted
    setup_pane.refresh()
    assert setup_pane.statuses["Extra-column volume"].accepted


def test_step_diagrams_mark_each_observation_point(study):
    guide = DEFAULT_CHAIN[1]
    comparisons = [c for c in study.comparisons if c.experiment_type in guide.experiment_types]

    svg = step_diagrams_html(guide, comparisons)

    assert svg.count(DIAGRAM) == 2
    assert 'data-observe="tubing_detectors"' in svg
    assert 'data-observe="column"' in svg
    assert step_diagrams_html(guide).count(DIAGRAM) == 2


def test_system_card_summarizes_the_setup_and_links_to_the_system_pane(study):
    import dataclasses

    recipe = study.comparisons[0].recipe
    calls = []
    setup_pane = CharacterizationSetupWidget(
        study, system=lambda: recipe,
        on_navigate=lambda target, context: calls.append((target, context)),
    )
    html = setup_pane._system_card.children[0].children[1].value

    assert "0. Your system" in setup_pane._system_card.children[0].children[0].children[0].value
    assert recipe.column_key in html and "<svg" in html
    assert "cadetgui-msg-warn" not in html
    setup_pane.buttons["system"].click()
    assert calls == [("system", {})]

    other = dataclasses.replace(recipe, column_key="General Rate Model (GRM)")
    setup_pane._system = lambda: other
    setup_pane.refresh_system()
    assert "different column model" in setup_pane._system_card.children[0].children[1].value


def test_no_system_card_without_a_system_source(study):
    assert CharacterizationSetupWidget(study)._system_card.children == ()


def test_system_card_shows_hardware_flow_rate_and_column_settings_but_no_template(study):
    recipe = study.comparisons[0].recipe
    setup_pane = CharacterizationSetupWidget(study, system=lambda: recipe)
    html = setup_pane._system_card.children[0].children[1].value

    assert "Process template" not in html and recipe.template_key not in html
    for row in ("Flow path", "Bypassed", "Sample loop", "Flow rate", "Column model",
                "Binding model", "Used by measurements"):
        assert row in html
    assert "mL/min" in html


def test_system_card_lists_the_column_settings_every_measurement_starts_from(study):
    import dataclasses

    recipe = dataclasses.replace(
        study.comparisons[0].recipe,
        column_values={"length": 0.1, "diameter": 0.0077, "bed_porosity": 0.35},
    )
    setup_pane = CharacterizationSetupWidget(study, system=lambda: recipe)
    html = setup_pane._system_card.children[0].children[1].value

    assert "length 10 cm · diameter 7.7 mm · bed porosity 0.35" in html


def test_step_cards_say_how_their_runs_use_the_system(study):
    setup_pane = CharacterizationSetupWidget(study)

    periphery = _card_text(setup_pane, 0)
    assert runs_use_text("system_pulse") in periphery
    assert "Runs use: Pulse Injection · column bypassed · read at" in periphery
    packing = _card_text(setup_pane, 1)
    assert packing.count("Runs use:") == 2
    assert "column in line" in packing and "(conductivity)" in packing
    assert "Runs use: Load–Wash–Elute (LWE) · column in line" in _card_text(setup_pane, 3)


def test_only_the_current_step_is_expanded_and_toggles_survive_a_refresh(study):
    setup_pane = CharacterizationSetupWidget(study)
    shown = {k: d.layout.display == "" for k, d in setup_pane.details.items()}
    assert shown["system_periphery"] and not shown["column_packing"]

    card = setup_pane._cards.children[1]
    card.children[0].children[0].children[0].click()
    assert setup_pane.details["column_packing"].layout.display == ""
    setup_pane.refresh(force=True)
    assert setup_pane.details["column_packing"].layout.display == ""
