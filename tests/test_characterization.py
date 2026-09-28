from __future__ import annotations

import copy
import threading
import warnings

import cadetgui.configuration_store as configuration_store
import numpy as np
import pytest
from cadetgui.cadetprocessadapter import (
    COLUMN_MODELS,
    INSTRUMENT_TEMPLATES,
    measurable_signal_options,
)
from cadetgui.widgets.composite import (
    CharacterizationWidget,
    ConfigurationWidget,
    InstrumentWidget,
    ParameterHistoryWidget,
)
from cadetgui.widgets.composite._characterization_stages import stage_spec
from cadetgui.widgets.composite.data_import import ExperimentalDataset

warnings.filterwarnings("ignore", category=UserWarning)

LRM = "Lumped Rate Model Without Pores (LRM)"
LRMP = "Lumped Rate Model With Pores (LRMP)"


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Redirect the configuration store to a tmp dir -- never touch the real one."""
    monkeypatch.setattr(configuration_store, "default_store_dir", lambda: tmp_path)


@pytest.fixture
def _synchronous_threads(monkeypatch):
    """Run the optimizer run's worker and ticker threads inline, in order."""
    monkeypatch.setattr(threading.Thread, "start", lambda self: self.run())


def _built_with_instrument(*, column_key: str = LRM):
    iw = InstrumentWidget()
    cw = ConfigurationWidget(instrument=iw)
    cw._model_picker.value = INSTRUMENT_TEMPLATES["Pulse Injection"]
    if column_key != LRM:
        cw._column_picker.value = COLUMN_MODELS[column_key]
    return iw, cw


def _periphery_widget(**kwargs):
    iw, cw = _built_with_instrument()
    iw._unit_checkboxes["tubing_pre_injection"].value = True
    w = CharacterizationWidget(
        "periphery", config=cw, instrument=iw, tubing_unit="tubing_pre_injection", **kwargs
    )
    return iw, cw, w


def _dataset(label: str, *, center: float = 8.0) -> ExperimentalDataset:
    t = np.linspace(0, 20, 40)
    y = np.exp(-((t - center) ** 2) / 4)
    return ExperimentalDataset(label=label, time_min=t, signal=y)


def _load(w: CharacterizationWidget, *datasets: ExperimentalDataset) -> None:
    """Import `datasets`, select them all and pick the first signal position."""
    w.data.datasets.extend(datasets)
    w._refresh_dataset_options()
    w._dataset_select.value = tuple(w.data.datasets)
    w._signal_picker.selected_index = 0


@pytest.fixture(scope="module")
def seeded_process():
    """LRMP + SMA process with the periphery units, for the pure stage-spec tests."""
    from cadetgui.widgets.composite import CharacterizationWorkbenchWidget

    return CharacterizationWorkbenchWidget().configuration.process


# -- stage specs ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stage", "tubing_unit", "match"),
    [("periphery", None, "requires tubing_unit"), ("bed", "tubing_pre_injection", "only applies")],
)
def test_tubing_unit_is_required_for_periphery_and_rejected_elsewhere(stage, tubing_unit, match):
    with pytest.raises(ValueError, match=match):
        stage_spec(stage, tubing_unit)


def test_widget_requires_an_instrument_for_instrument_write_backs():
    _, cw = _built_with_instrument()
    with pytest.raises(ValueError, match="instrument"):
        CharacterizationWidget("periphery", config=cw, tubing_unit="tubing_pre_injection")


@pytest.mark.parametrize(
    ("stage", "tubing_unit", "expected"),
    [
        (
            "periphery", "tubing_detectors",
            {"tubing_detectors_length", "tubing_detectors_axial_dispersion"},
        ),
        ("pre_injection", None, {"tubing_pre_injection_length", "mixer_volume"}),
        ("bed", None, {"bed_porosity", "axial_dispersion"}),
        ("particles", None, {"film_diffusion"}),
        ("adsorption", None, {"characteristic_charge", "adsorption_rate"}),
        ("capacity", None, {"capacity"}),
    ],
)
def test_every_stage_writes_back_exactly_its_fitted_variables(stage, tubing_unit, expected):
    spec = stage_spec(stage, tubing_unit)

    assert {f.name for f in spec.fields} == expected
    assert set(spec.write_targets) == expected


def test_mixer_volume_lands_on_the_mixers_liquid_volume(seeded_process):
    process = copy.deepcopy(seeded_process)
    spec = stage_spec("pre_injection")

    spec.apply_values(process, {"mixer_volume": 3e-6, "tubing_pre_injection_length": 0.7})

    assert process.flow_sheet["mixer"].init_liquid_volume == pytest.approx(3e-6)
    assert process.flow_sheet["tubing_pre_injection"].length == pytest.approx(0.7)
    assert spec.read_values(process) == pytest.approx(
        {"mixer_volume": 3e-6, "tubing_pre_injection_length": 0.7}
    )


def test_scalar_and_per_component_list_attributes_round_trip(seeded_process):
    process = copy.deepcopy(seeded_process)
    binding = process.flow_sheet.column.binding_model
    assert isinstance(binding.characteristic_charge, list)
    assert isinstance(binding.capacity, float)

    for stage, values in (
        ("adsorption", {"characteristic_charge": 4.5, "adsorption_rate": 2.0}),
        ("capacity", {"capacity": 321.0}),
    ):
        spec = stage_spec(stage)
        spec.apply_values(process, values)
        assert spec.read_values(process) == pytest.approx(values)

    assert binding.characteristic_charge == [4.5]
    assert binding.capacity == pytest.approx(321.0)


def test_group_by_form_splits_values_per_target_form_and_unit():
    spec = stage_spec("pre_injection")

    groups = spec.group_by_form(
        {"mixer_volume": 1e-6, "tubing_pre_injection_length": 0.5, "unrelated": 1.0}
    )

    assert groups == {
        ("instrument", "mixer"): {"init_liquid_volume": 1e-6},
        ("instrument", "tubing_pre_injection"): {"length": 0.5},
    }


# -- widget: validation and run spec ----------------------------------------------------


def test_bounds_default_from_the_field_specs_and_must_be_ordered():
    _, _, w = _periphery_widget()
    _load(w, _dataset("d1"))
    lb, ub = w._bound_fields["tubing_pre_injection_length"]
    assert (lb.value, ub.value) == (pytest.approx(1e-3), pytest.approx(5.0))
    assert w._validation_error() is None

    lb.value, ub.value = 2.0, 1.0

    assert "bound" in w._validation_error().lower()


@pytest.mark.parametrize(
    ("calibration", "field", "value", "expected"),
    [
        ("beer_lambert", "_extinction_field", 0.0, "extinction"),
        ("beer_lambert", "_path_length_field", -1.0, "path length"),
        ("normalize_area", "_target_area_field", 0.0, "injected amount"),
    ],
)
def test_calibration_inputs_are_validated(calibration, field, value, expected):
    _, _, w = _periphery_widget()
    _load(w, _dataset("d1"))
    w._calibration_picker.value = calibration
    getattr(w, field).value = value

    assert expected in w._validation_error().lower()


def test_validation_asks_for_a_dataset_first():
    _, _, w = _periphery_widget()

    assert "dataset" in w._validation_error().lower()


def test_the_calibration_choice_shows_its_inputs_and_calibrates_the_reference():
    _, cw = _built_with_instrument(column_key=LRMP)
    w = CharacterizationWidget("bed", config=cw)
    _load(w, _dataset("d1"))
    _, _, raw = w._build_problem("outlet.outlet")
    assert w._beer_lambert_box.layout.display == "none"

    w._calibration_picker.value = "normalize_area"
    w._target_area_field.value = 5.0
    _, _, normalized = w._build_problem("outlet.outlet")

    assert w._normalize_area_box.layout.display == ""
    assert w._beer_lambert_box.layout.display == "none"
    assert w._calibration_kwargs() == {"target_area": 5.0}
    area = np.trapezoid(normalized[0].solution[:, 0], normalized[0].time)
    assert area == pytest.approx(5.0)
    assert not np.allclose(raw[0].solution, normalized[0].solution)


def test_component_picker_offers_the_configurations_components():
    _, cw = _built_with_instrument(column_key=LRMP)
    cw.components = ["Salt", "Protein"]
    w = CharacterizationWidget("bed", config=cw)

    assert w._component_picker.option_labels == ["Salt", "Protein", "Total (sum of all components)"]


def test_a_joint_problem_gets_one_uniquely_named_process_per_dataset():
    _, cw = _built_with_instrument(column_key=LRMP)
    w = CharacterizationWidget("bed", config=cw)
    _load(w, _dataset("d0"), _dataset("d1", center=9.0))

    problem, processes, references = w._build_problem("outlet.outlet")

    assert len({p.name for p in processes}) == 2
    assert all(p is not cw.process for p in processes)
    assert [r.name for r in references] == ["d0", "d1"]
    assert problem.variable_names == ["bed_porosity", "axial_dispersion"]
    assert problem.callbacks == []


def test_the_run_spec_starts_at_the_bound_midpoints_and_previews_interactively():
    _, cw = _built_with_instrument(column_key=LRMP)
    w = CharacterizationWidget("bed", config=cw)
    _load(w, _dataset("d1"))

    spec = w._build_run_spec()

    assert spec.x0 == pytest.approx([(0.2 + 0.8) / 2, (1e-12 + 1e-4) / 2])
    series = spec.preview_series([lb.value for lb, _ in w._bound_fields.values()])
    assert series
    measured = [s for s in series if s.get("reference")]
    assert [s["name"] for s in measured] == ["measured (dataset 1)"]


def test_the_run_spec_reports_a_validation_error_instead_of_raising():
    _, cw = _built_with_instrument(column_key=LRMP)
    w = CharacterizationWidget("bed", config=cw)

    assert "dataset" in w._build_run_spec().lower()


def test_accept_button_is_labelled_for_pushing_to_the_configuration():
    _, cw = _built_with_instrument(column_key=LRMP)
    w = CharacterizationWidget("bed", config=cw)

    assert w._runner._btn_accept.description == "Push to Configuration"
    assert w._runner.root in w.root.children
    assert w.status is w._runner.status


def test_signal_options_are_the_measurable_positions_and_follow_the_flow_path():
    iw, cw = _built_with_instrument(column_key=LRMP)
    w = CharacterizationWidget("bed", config=cw)
    expected = [label for label, _ in measurable_signal_options(cw.process)]
    assert w._signal_picker.option_labels == expected
    assert "Tubing (detectors) outlet" not in expected

    iw._unit_checkboxes["tubing_detectors"].value = True

    assert "Tubing (detectors) outlet" in w._signal_picker.option_labels


# -- real fits --------------------------------------------------------------------------


@pytest.mark.slow
def test_periphery_fit_accept_writes_the_unit_form_and_records_history(_synchronous_threads):
    history = ParameterHistoryWidget()
    iw, _, w = _periphery_widget(history=history)
    _load(w, _dataset("pulse"))
    w._runner._knob_fields["Nelder-Mead"][0].value = 15
    before = iw._unit_forms["tubing_pre_injection"].collect_values()

    w._runner._on_run(None)

    result = w._runner._last_result
    assert result is not None
    assert result.success
    assert set(result.x_best) == {
        "tubing_pre_injection_length", "tubing_pre_injection_axial_dispersion",
    }
    assert history.pushes == []  # nothing recorded before an explicit accept

    w._runner._on_accept(None)

    after = iw._unit_forms["tubing_pre_injection"].collect_values()
    assert after["length"] == pytest.approx(result.x_best["tubing_pre_injection_length"])
    assert after["axial_dispersion"] == pytest.approx(
        result.x_best["tubing_pre_injection_axial_dispersion"]
    )
    assert after["diameter"] == before["diameter"]  # unrelated fields are left alone
    (push,) = history.pushes
    assert push.stage == "periphery"
    assert push.dataset_labels == ["pulse"]
    assert push.optimizer_name == "Nelder-Mead"
    assert push.objective == pytest.approx(result.objective)
    assert push.values == pytest.approx(
        {
            "tubing_pre_injection_length": after["length"],
            "tubing_pre_injection_axial_dispersion": after["axial_dispersion"],
        }
    )


@pytest.mark.slow
def test_bed_stage_joint_fits_two_datasets_with_a_multi_objective_optimizer_and_accepts(
    _synchronous_threads,
):
    _, cw = _built_with_instrument(column_key=LRMP)
    w = CharacterizationWidget("bed", config=cw)
    _load(w, _dataset("d0", center=8.0), _dataset("d1", center=9.0))

    # One objective per dataset: Nelder-Mead can't solve that, U-NSGA-III can.
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
    assert after["particle_porosity"] == before  # unrelated column fields are left alone
