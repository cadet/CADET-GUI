from __future__ import annotations

import shutil
import warnings
from dataclasses import replace
from pathlib import Path

import pytest
from cadetgui.parameter_store import ParameterStore, Provenance
from cadetgui.study import Study
from cadetgui.widgets.composite import ParameterStoreWidget
from cadetgui.widgets.composite.parameter_store_view import (
    chain_warnings,
    parameter_label,
)

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

MANIFEST = (
    Path(__file__).parent.parent / "examples" / "data" / "characterization_akta" / "manifest.json"
)
LENGTH = "flow_sheet.tubing_pre_column.length"
DISPERSION = "flow_sheet.tubing_pre_column.axial_dispersion"
FILM = "flow_sheet.column.film_diffusion"
POROSITY = "flow_sheet.column.bed_porosity"


@pytest.fixture
def study() -> Study:
    return Study.load(MANIFEST)


@pytest.fixture
def view(study) -> ParameterStoreWidget:
    return ParameterStoreWidget(study)


def accept_periphery(study: Study) -> None:
    study.accept("Extra-column volume", study.initial_store.updated(
        {LENGTH: 0.42, DISPERSION: {"SystemTracer": 4.5e-7}},
        Provenance(
            step="Extra-column volume",
            probe="SystemTracer",
            source="System pulse 1 (UV), System pulse 2 (UV)",
            metric={"System pulse 1 (UV)_NRMSE": 0.01, "System pulse 2 (UV)_NRMSE": 0.02},
        ),
    ))


def rows_by_label(view: ParameterStoreWidget) -> dict:
    return {
        label: [cell["text"] for cell in row]
        for label, row in zip(view._table.option_labels, view._table.rows)
    }


def test_friendly_labels():
    assert parameter_label(LENGTH) == "Tubing (pre column) · length"
    assert parameter_label("flow_sheet.unknown.x") == "flow_sheet.unknown.x"


def test_lists_the_initial_store_one_row_per_species(view):
    rows = rows_by_label(view)
    assert rows[f"{FILM} SmallTracer"][:5] == [
        "Column · film diffusion", FILM, "SmallTracer", "8e-05", "initial",
    ]
    assert f"{FILM} LargeTracer" in rows
    assert rows["flow_sheet.column.particle_radius"][2] == ""
    assert rows["flow_sheet.column.particle_radius"][8].startswith("known hardware")


def test_refreshes_on_accept_and_shows_any_step(view, study):
    accept_periphery(study)

    rows = rows_by_label(view)
    assert rows[LENGTH][3] == "0.42"
    assert rows[LENGTH][4:8] == [
        "Extra-column volume",
        "SystemTracer",
        "System pulse 1 (UV), System pulse 2 (UV)",
        "System pulse 1 (UV)_NRMSE 0.01, System pulse 2 (UV)_NRMSE 0.02",
    ]
    assert view._step_picker.option_labels == [
        "Current (after the last accepted step)", "Initial",
        "After Extra-column volume", "After Column packing (not accepted)",
    ]

    view.show_after("")
    assert view.get_value() is study.initial_store
    assert LENGTH not in rows_by_label(view)
    view.show_after("Column packing")
    assert view.get_value() is study.posteriors["Extra-column volume"]


def test_chain_warnings(view, study):
    assert chain_warnings(study) == []

    study.upsert_step(replace(study.steps[0], requires=(POROSITY,)))
    warnings_ = chain_warnings(study)
    assert any("no earlier step provides" in w for w in warnings_)
    assert any("not in the store it starts from" in w for w in warnings_)
    assert POROSITY in view._warnings.value

    study.upsert_step(replace(study.steps[0], requires=()))
    study.upsert_step(replace(study.steps[1], requires=(LENGTH,)))
    assert [w for w in chain_warnings(study) if "no earlier step" in w] == []
    assert any("not in the store it starts from" in w for w in chain_warnings(study))
    accept_periphery(study)
    assert chain_warnings(study) == []


def test_incomplete_step_is_reported_not_raised(study):
    study.upsert_step(replace(study.steps[0], options={}))
    assert any("incomplete" in w for w in chain_warnings(study))


def test_save_and_load_replace_the_study_in_place(view, study, tmp_path):
    for comparison in study.comparisons:
        shutil.copy(MANIFEST.parent / comparison.data_file, tmp_path / comparison.data_file)
    accept_periphery(study)
    view._path.value = str(tmp_path / "study.json")
    view._btn_save.click()
    assert "cadetgui-msg-ok" in view.status.value

    other = Study.load(MANIFEST)
    calls = []
    other.add_listener(lambda: calls.append(1))
    other_view = ParameterStoreWidget(other)
    assert not other.posteriors

    other_view.load_study(tmp_path / "study.json")

    assert calls == [1]
    assert other.posteriors["Extra-column volume"].value(LENGTH) == 0.42
    assert other.base_dir == tmp_path
    assert all(c.run is not None for c in other.comparisons)
    assert rows_by_label(other_view)[LENGTH][3] == "0.42"


def test_load_error_is_shown(view, tmp_path):
    view._path.value = str(tmp_path / "missing.json")
    view._btn_load.click()
    assert "cadetgui-msg-error" in view.status.value


def test_exports_the_current_store(view, study, tmp_path):
    accept_periphery(study)
    view._store_path.value = str(tmp_path / "store.json")
    view._btn_export.click()
    assert ParameterStore.load(tmp_path / "store.json") == study.current_store


def test_implied_values_are_labelled_as_assumed_by_the_experiment_type(study):
    from cadetgui.characterization_guide import EXPERIMENT_TYPES, with_implied_values
    from cadetgui.widgets.composite.parameter_store_view import set_by_label

    study.initial_store = with_implied_values(
        study.initial_store, EXPERIMENT_TYPES["column_pulse_large_tracer"], "Dextran"
    )
    view = ParameterStoreWidget(study)

    row = rows_by_label(view)[f"{FILM} Dextran"]
    assert row[4] == "Assumed by experiment type: Column pulse, large tracer (UV)"
    assert set_by_label("Extra-column volume") == "Extra-column volume"
    assert "data-tip=" in view.root.children[1].value
