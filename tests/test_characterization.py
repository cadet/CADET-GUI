from __future__ import annotations

import threading
import warnings

import cadetgui.configuration_store as configuration_store
import numpy as np
import pytest
from cadetgui.cadetprocessadapter import COLUMN_MODELS, INSTRUMENT_TEMPLATES
from cadetgui.widgets.composite import (
    CharacterizationWidget,
    ConfigurationWidget,
    InstrumentWidget,
    ParameterHistoryWidget,
)
from cadetgui.widgets.composite.data_import import ExperimentalDataset

warnings.filterwarnings("ignore", category=UserWarning)


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Redirect the configuration store to a tmp dir -- never touch the real one."""
    monkeypatch.setattr(configuration_store, "default_store_dir", lambda: tmp_path)


@pytest.fixture
def _synchronous_threads(monkeypatch):
    """Same pattern as tests/test_parameter_estimation.py's fixture of the same
    name -- makes the run's worker+ticker threads run inline and in order."""
    monkeypatch.setattr(threading.Thread, "start", lambda self: self.run())


def _built_with_instrument(*, column_key: str = "Lumped Rate Model Without Pores (LRM)"):
    iw = InstrumentWidget()
    cw = ConfigurationWidget(instrument=iw)
    cw._model_picker.value = INSTRUMENT_TEMPLATES["Pulse Injection"]
    if column_key != "Lumped Rate Model Without Pores (LRM)":
        cw._column_picker.value = COLUMN_MODELS[column_key]
    return iw, cw


def _dataset(label: str, *, center: float = 8.0) -> ExperimentalDataset:
    t = np.linspace(0, 20, 40)
    y = np.exp(-((t - center) ** 2) / 4)
    return ExperimentalDataset(label=label, time_min=t, signal=y)


def test_periphery_stage_requires_tubing_unit():
    _, cw = _built_with_instrument()
    with pytest.raises(ValueError, match="tubing_unit"):
        CharacterizationWidget("periphery", config=cw)


def test_tubing_unit_is_rejected_for_non_periphery_stages():
    _, cw = _built_with_instrument()
    with pytest.raises(ValueError, match="tubing_unit"):
        CharacterizationWidget("bed", config=cw, tubing_unit="tubing_pre_injection")


def test_instrument_writeback_stage_requires_instrument():
    _, cw = _built_with_instrument()
    with pytest.raises(ValueError, match="instrument"):
        CharacterizationWidget("periphery", config=cw, tubing_unit="tubing_pre_injection")


def test_stage_not_needing_instrument_writeback_does_not_require_one():
    _, cw = _built_with_instrument(column_key="Lumped Rate Model With Pores (LRMP)")
    # Must not raise -- "bed" only writes back to the column, no instrument needed.
    CharacterizationWidget("bed", config=cw)


def test_validation_error_reports_missing_dataset_and_signal():
    iw, cw = _built_with_instrument()
    iw._unit_checkboxes["tubing_pre_injection"].value = True
    w = CharacterizationWidget(
        "periphery", config=cw, instrument=iw, tubing_unit="tubing_pre_injection"
    )
    assert "dataset" in w._validation_error().lower()

    w.data.datasets.append(_dataset("d1"))
    w._refresh_dataset_options()
    w._dataset_select.value = tuple(w.data.datasets)
    # The signal picker is populated from the process itself, so with a
    # dataset picked nothing is left missing.
    assert w._validation_error() is None


def test_bound_fields_default_from_field_spec_min_max():
    iw, cw = _built_with_instrument()
    iw._unit_checkboxes["tubing_pre_injection"].value = True
    w = CharacterizationWidget(
        "periphery", config=cw, instrument=iw, tubing_unit="tubing_pre_injection"
    )
    lb, ub = w._bound_fields["tubing_pre_injection_length"]
    assert lb.value == pytest.approx(1e-3)
    assert ub.value == pytest.approx(5.0)


def test_bounds_must_be_ordered():
    iw, cw = _built_with_instrument()
    iw._unit_checkboxes["tubing_pre_injection"].value = True
    w = CharacterizationWidget(
        "periphery", config=cw, instrument=iw, tubing_unit="tubing_pre_injection"
    )
    w.data.datasets.append(_dataset("d1"))
    w._refresh_dataset_options()
    w._dataset_select.value = tuple(w.data.datasets)
    w._signal_picker.selected_index = 0

    lb, ub = w._bound_fields["tubing_pre_injection_length"]
    lb.value, ub.value = 2.0, 1.0

    assert "bound" in w._validation_error().lower()


@pytest.mark.slow
def test_periphery_stage_fits_and_accept_writes_into_the_instrument_unit_form(
    _synchronous_threads,
):
    iw, cw = _built_with_instrument()
    iw._unit_checkboxes["tubing_pre_injection"].value = True
    w = CharacterizationWidget(
        "periphery", config=cw, instrument=iw, tubing_unit="tubing_pre_injection"
    )
    w.data.datasets.append(_dataset("pulse"))
    w._refresh_dataset_options()
    w._dataset_select.value = tuple(w.data.datasets)
    w._signal_picker.selected_index = 0
    w._runner._knob_fields["Nelder-Mead"][0].value = 15

    before = iw._unit_forms["tubing_pre_injection"].collect_values()
    w._runner._on_run(None)

    result = w._runner._last_result
    assert result is not None
    assert result.success
    assert set(result.x_best) == {
        "tubing_pre_injection_length", "tubing_pre_injection_axial_dispersion",
    }

    w._runner._on_accept(None)
    after = iw._unit_forms["tubing_pre_injection"].collect_values()
    assert after["length"] == pytest.approx(result.x_best["tubing_pre_injection_length"])
    assert after["axial_dispersion"] == pytest.approx(
        result.x_best["tubing_pre_injection_axial_dispersion"]
    )
    # Unrelated fields on the same unit are left untouched by the merge.
    assert after["diameter"] == before["diameter"]


@pytest.mark.slow
def test_accept_records_a_history_entry_with_provenance_and_confirmed_values(
    _synchronous_threads,
):
    iw, cw = _built_with_instrument()
    iw._unit_checkboxes["tubing_pre_injection"].value = True
    history = ParameterHistoryWidget()
    w = CharacterizationWidget(
        "periphery", config=cw, instrument=iw, tubing_unit="tubing_pre_injection",
        history=history,
    )
    w.data.datasets.append(_dataset("pulse"))
    w._refresh_dataset_options()
    w._dataset_select.value = tuple(w.data.datasets)
    w._signal_picker.selected_index = 0
    w._runner._knob_fields["Nelder-Mead"][0].value = 15
    w._runner._on_run(None)

    assert history.pushes == []  # nothing recorded before an explicit accept

    w._runner._on_accept(None)

    assert len(history.pushes) == 1
    push = history.pushes[0]
    assert push.stage == "periphery"
    assert push.dataset_labels == ["pulse"]
    assert push.optimizer_name == "Nelder-Mead"
    assert push.objective is not None
    unit_form_values = iw._unit_forms["tubing_pre_injection"].collect_values()
    assert push.values["tubing_pre_injection_length"] == pytest.approx(unit_form_values["length"])
    assert push.values["tubing_pre_injection_axial_dispersion"] == pytest.approx(
        unit_form_values["axial_dispersion"]
    )


@pytest.mark.slow
def test_bed_stage_joint_fits_two_datasets_with_a_multi_objective_optimizer_and_accepts(
    _synchronous_threads,
):
    _, cw = _built_with_instrument(column_key="Lumped Rate Model With Pores (LRMP)")
    w = CharacterizationWidget("bed", config=cw)
    w.data.datasets.append(_dataset("d0", center=8.0))
    w.data.datasets.append(_dataset("d1", center=9.0))
    w._refresh_dataset_options()
    w._dataset_select.value = tuple(w.data.datasets)
    w._signal_picker.selected_index = 0

    # Nelder-Mead can't solve a genuinely multi-objective problem (one
    # objective per dataset here) -- U-NSGA-III is required for a real joint
    # multi-experiment fit, which is the whole point of this stage.
    w._runner._optimizer_picker.value = "U-NSGA-III"
    pop_field, gen_field = w._runner._knob_fields["U-NSGA-III"]
    pop_field.value = 6
    gen_field.value = 3

    w._runner._on_run(None)

    result = w._runner._last_result
    assert result is not None
    assert result.success
    assert set(result.x_best) == {"bed_porosity", "axial_dispersion"}

    before = cw._column_form.collect_values()["particle_porosity"]
    w._runner._on_accept(None)
    after = cw._column_form.collect_values()
    assert after["bed_porosity"] == pytest.approx(result.x_best["bed_porosity"])
    assert after["axial_dispersion"] == pytest.approx(result.x_best["axial_dispersion"])
    # Unrelated column fields are left untouched by the merge.
    assert after["particle_porosity"] == before


def test_signal_picker_offers_only_measurable_positions_without_a_preview():
    iw, cw = _built_with_instrument(column_key="Lumped Rate Model With Pores (LRMP)")
    w = CharacterizationWidget("bed", config=cw)

    labels = w._signal_picker.option_labels

    # Populated straight from the process -- no simulation needed first.
    assert labels
    assert labels[0] == "Outlet"
    assert "Column outlet" in labels
    # Inputs and hardware-internal ports are not places a detector sits.
    assert not any(label.startswith(("Buffer", "Feed")) for label in labels)
    assert not any(label.endswith(" inlet") for label in labels)
    assert not any(label.startswith(("Mixer", "Sample loop")) for label in labels)
    assert not any(label.endswith(" volume") for label in labels)


def test_signal_options_follow_the_configuration_flow_path():
    iw, cw = _built_with_instrument(column_key="Lumped Rate Model With Pores (LRMP)")
    w = CharacterizationWidget("bed", config=cw)
    assert "Tubing (detectors) outlet" not in w._signal_picker.option_labels

    iw._unit_checkboxes["tubing_detectors"].value = True

    assert "Tubing (detectors) outlet" in w._signal_picker.option_labels
