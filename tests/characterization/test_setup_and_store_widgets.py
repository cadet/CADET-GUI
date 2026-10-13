"""Setup, components, parameter store and guide widgets over a shared Study."""
from __future__ import annotations

import dataclasses
import shutil

import pytest
from cadetgui.characterization.guide import (
    DEFAULT_CHAIN,
    EXPERIMENT_TYPES,
    with_implied_values,
)
from cadetgui.characterization.parameter_store import ParameterStore
from cadetgui.characterization.runner import StepSetup
from cadetgui.characterization.study import Study, StudyComponent
from cadetgui.widgets.characterization import (
    CharacterizationGuideWidget,
    CharacterizationSetupWidget,
    ParameterStoreWidget,
    StudyComponentsWidget,
)
from cadetgui.widgets.characterization.components import bind_study_components
from cadetgui.widgets.characterization.guide import markdown_html
from cadetgui.widgets.characterization.help import term_html
from cadetgui.widgets.characterization.parameter_store import chain_warnings
from cadetgui.widgets.characterization.setup import (
    ADD_ANOTHER,
    ADD_MEASUREMENT,
    OPEN_STEP,
    TRANSFER,
    set_up_label,
    step_diagrams_html,
)
from cadetgui.widgets.instrument import InstrumentWidget

from characterization.synthetic import DATA_DIR, FILM, LENGTH

POROSITY = "flow_sheet.column.bed_porosity"
EXAMPLE = ["SystemTracer", "SmallTracer", "LargeTracer"]


def protein_pulse(study, name="Protein pulse 1"):
    large = study.comparison("Large tracer pulse 1 (UV)")
    return dataclasses.replace(large, name=name, experiment_type="nonbinding_protein_pulse")


def labels(setup):
    return {key: button.description for key, button in setup.buttons.items()}


class TestSetup:
    def test_buttons_follow_each_steps_status(self, study, accept_periphery):
        setup = CharacterizationSetupWidget(study)
        assert list(setup.buttons) == [g.id for g in DEFAULT_CHAIN]
        assert labels(setup) == {
            "system_periphery": OPEN_STEP, "column_packing": OPEN_STEP,
            "particle_transport": ADD_MEASUREMENT, "binding": ADD_MEASUREMENT,
            "capacity": ADD_MEASUREMENT,
        }
        assert setup.statuses["Extra-column volume"].ready

        accept_periphery()

        assert setup.statuses["Extra-column volume"].accepted
        assert labels(setup)["column_packing"] == TRANSFER

    @pytest.mark.parametrize("key, target", [
        ("column_packing", ("step", {"name": "Column packing"})),
        ("particle_transport", ("measurements", {"step_id": "particle_transport"})),
        ("system", ("system", {})),
    ])
    def test_buttons_navigate(self, study, navigation, key, target):
        recipe = study.comparisons[0].recipe
        setup = CharacterizationSetupWidget(study, on_navigate=navigation, system=lambda: recipe)
        setup.buttons[key].click()
        assert navigation.calls == [target]

    def test_set_up_adds_the_step_with_its_measurements_in_chain_order(self, study, navigation):
        setup = CharacterizationSetupWidget(study, on_navigate=navigation)
        notified = []
        setup.add_listener(lambda: notified.append(1))
        study.upsert_comparison(protein_pulse(study))
        assert setup.buttons["particle_transport"].description == set_up_label(1)
        setup.secondary_buttons["particle_transport"].click()
        assert setup.secondary_buttons["particle_transport"].description == ADD_ANOTHER

        setup.buttons["particle_transport"].click()

        assert study.steps[-1].name == "Particle transport"
        assert study.steps[-1].stage == "particles"
        assert [c.name for c in study.steps[-1].comparisons] == ["Protein pulse 1"]
        assert navigation.calls == [
            ("measurements", {"step_id": "particle_transport"}),
            ("step", {"name": "Particle transport"}),
        ]
        assert notified == [1]

        empty = Study()
        CharacterizationSetupWidget(empty).set_up("binding")
        CharacterizationSetupWidget(empty).set_up("system_periphery")
        assert [s.name for s in empty.steps] == ["Extra-column volume", "Binding"]

    def test_custom_steps_get_a_card_and_are_added_by_name(self, navigation):
        study = Study()
        study.upsert_step(StepSetup(name="mine", stage="tubing",
                                    options={"tubing": "tubing_detectors"}))
        setup = CharacterizationSetupWidget(study, on_navigate=navigation)
        assert setup.buttons["mine"].description == OPEN_STEP

        assert setup.add_step("fit", "bed") == "fit"
        assert navigation.calls == [("step", {"name": "fit"})]
        with pytest.raises(ValueError, match="already exists"):
            setup.add_step("fit")

    def test_fitted_steps_and_manual_refresh(self, study):
        fitted: set = set()
        setup = CharacterizationSetupWidget(study, fitted_steps=lambda: fitted,
                                            auto_refresh=False)
        fitted.add("Extra-column volume")
        study.accept("Column packing", study.initial_store)
        assert setup.stale and not setup.statuses["Column packing"].accepted

        setup.refresh()

        assert setup.statuses["Extra-column volume"].fitted
        assert setup.statuses["Column packing"].accepted

    def test_system_card_follows_the_system_and_flags_another_column_model(self, study):
        recipe = study.comparisons[0].recipe
        current = [recipe]
        setup = CharacterizationSetupWidget(study, system=lambda: current[0])
        assert "different column model" not in setup._system_card.children[0].children[1].value

        current[0] = dataclasses.replace(recipe, column_key="General Rate Model (GRM)")
        setup.refresh_system()

        assert "different column model" in setup._system_card.children[0].children[1].value
        assert CharacterizationSetupWidget(study)._system_card.children == ()

    def test_step_diagrams_mark_each_observation_point(self, study):
        guide = DEFAULT_CHAIN[1]
        tagged = [c for c in study.comparisons if c.experiment_type in guide.experiment_types]
        svg = step_diagrams_html(guide, tagged)
        assert 'data-observe="tubing_detectors"' in svg and 'data-observe="column"' in svg


def rows_by_label(view: ParameterStoreWidget) -> dict:
    return {
        label: [cell["text"] for cell in row]
        for label, row in zip(view._table.option_labels, view._table.rows)
    }


class TestParameterStore:
    def test_rows_per_species_follow_accepts_and_the_chosen_step(self, study, accept_periphery):
        view = ParameterStoreWidget(study)
        notified = []
        view.add_listener(lambda: notified.append(1))
        rows = rows_by_label(view)
        assert rows[f"{FILM} SmallTracer"][2:5] == ["SmallTracer", "8e-5", "initial"]
        assert f"{FILM} LargeTracer" in rows

        accept_periphery()

        assert notified
        assert rows_by_label(view)[LENGTH][3:8] == [
            "0.42", "Extra-column volume", "SystemTracer",
            "System pulse 1 (UV), System pulse 2 (UV)",
            "System pulse 1 (UV)_NRMSE 0.01, System pulse 2 (UV)_NRMSE 0.02",
        ]
        view.show_after("")
        assert view.get_value() is study.initial_store
        assert LENGTH not in rows_by_label(view)
        view.show_after("Column packing")
        assert view.get_value() is study.posteriors["Extra-column volume"]
        view.show_after(None)
        assert view.get_value() is study.current_store

    def test_implied_values_are_labelled_as_assumed(self, study):
        study.initial_store = with_implied_values(
            study.initial_store, EXPERIMENT_TYPES["column_pulse_large_tracer"], "Dextran"
        )
        row = rows_by_label(ParameterStoreWidget(study))[f"{FILM} Dextran"]
        assert row[4] == "Assumed by experiment type: Column pulse, large tracer (UV)"

    def test_chain_warnings(self, study, accept_periphery):
        view = ParameterStoreWidget(study)
        assert chain_warnings(study) == []

        study.upsert_step(dataclasses.replace(study.steps[0], requires=(POROSITY,)))
        found = chain_warnings(study)
        assert any("no earlier step provides" in w for w in found)
        assert any("not in the store it starts from" in w for w in found)
        assert POROSITY in view._warnings.value

        study.upsert_step(dataclasses.replace(study.steps[0], requires=()))
        study.upsert_step(dataclasses.replace(study.steps[1], requires=(LENGTH,)))
        assert all("no earlier step" not in w for w in chain_warnings(study))
        accept_periphery()
        assert chain_warnings(study) == []
        study.upsert_step(dataclasses.replace(study.steps[0], options={}))
        assert any("incomplete" in w for w in chain_warnings(study))

    def test_save_and_load_replace_the_study_in_place(self, study, accept_periphery, tmp_path):
        for comparison in study.comparisons:
            shutil.copy(DATA_DIR / comparison.data_file, tmp_path / comparison.data_file)
        accept_periphery()
        view = ParameterStoreWidget(study)
        view._path.value = str(tmp_path / "study.json")
        view._btn_save.click()
        assert "cadetgui-msg-ok" in view.status.value
        view._store_path.value = str(tmp_path / "store.json")
        view._btn_export.click()
        assert ParameterStore.load(tmp_path / "store.json") == study.current_store

        other = Study.load(DATA_DIR / "manifest.json")
        calls = []
        other.add_listener(lambda: calls.append(1))
        other_view = ParameterStoreWidget(other)
        other_view.load_study(tmp_path / "study.json")

        assert calls == [1]
        assert other.posteriors["Extra-column volume"].value(LENGTH) == 0.42
        assert other.base_dir == tmp_path
        assert all(c.run is not None for c in other.comparisons)
        assert rows_by_label(other_view)[LENGTH][3] == "0.42"

        other_view._path.value = str(tmp_path / "missing.json")
        other_view._btn_load.click()
        assert "cadetgui-msg-error" in other_view.status.value


class TestComponents:
    def test_adds_renames_changes_roles_and_removes(self, study):
        editor = StudyComponentsWidget(study)
        notified = []
        editor.add_listener(lambda: notified.append(1))
        assert list(editor.rows) == EXAMPLE
        assert editor.rows["SmallTracer"][2].disabled

        assert editor.add("IgGG", "protein")
        assert not editor.add("IgGG", "protein")
        assert "already declared" in editor.status.value
        editor.rows["IgGG"][0].value = "IgG"
        assert study.component("IgG") == StudyComponent("IgG", "protein")
        editor.rows["IgG"][1].value = "large tracer"
        assert study.component("IgG").role == "large tracer"
        editor.rows["IgG"][2].click()
        assert study.component("IgG") is None and "IgG" not in editor.rows
        assert len(notified) == 4

    def test_a_refused_change_is_reverted_and_explained(self, study):
        editor = StudyComponentsWidget(study)
        editor.rows["SmallTracer"][0].value = "Acetone"
        assert "cannot be renamed" in editor.status.value
        assert editor.rows["SmallTracer"][0].value == "SmallTracer"

        editor.rows["SmallTracer"][1].value = "salt"
        assert study.component("SmallTracer").role == "small tracer"
        assert editor.rows["SmallTracer"][1].value == "small tracer"
        assert "only the component named Salt" in editor.status.value

    def test_the_salt_role_fixes_the_name(self, study):
        editor = StudyComponentsWidget(study)
        editor._new_role.value = "salt"
        assert editor._new_name.value == "Salt" and editor._new_name.disabled
        editor._btn_add.click()
        assert study.component("Salt").role == "salt"
        name, role, _ = editor.rows["Salt"]
        assert name.disabled and role.disabled
        assert "salt" not in list(editor._new_role.options)

    def test_bound_instrument_follows_the_study(self, study):
        instrument = InstrumentWidget()
        editor = bind_study_components(instrument, study)
        assert instrument._components_field not in instrument._components_section.children
        assert editor.root in instrument._components_section.children
        assert instrument.components == EXAMPLE
        study.add_component("Salt", "salt")
        assert instrument.components == ["Salt", *EXAMPLE]


def test_guide_lists_every_chain_step_and_experiment_type():
    guide = CharacterizationGuideWidget()
    for step in DEFAULT_CHAIN:
        assert step.title in guide.chain.value
    for experiment in EXPERIMENT_TYPES.values():
        assert experiment.label in guide.experiment_types.value
    assert markdown_html("# T\n\nSome **bold**\ntext.\n\n1. one\n2. two\n\n- a\n") == (
        "<h3>T</h3><p>Some <b>bold</b> text.</p><ol><li>one</li><li>two</li></ol>"
        "<ul><li>a</li></ul>"
    )
    assert markdown_html("a < b") == "<p>a &lt; b</p>"


def test_terms_carry_their_glossary_tip():
    assert "data-tip=" in term_html("prior", label="x") and ">x</span>" in term_html("prior", "x")
    assert term_html("<nope>") == "&lt;nope&gt;"
    assert term_html("frozen variable") == term_html("fixed variable", "frozen variable")
