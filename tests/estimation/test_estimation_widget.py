"""ParameterEstimationWidget wiring: configuration, data, preview, run, accept."""
from __future__ import annotations

import cadetgui.widgets.estimation.estimation as estimation_module
import pytest
from cadetgui.process_model.simulation import run_process
from cadetgui.widgets.estimation import ParameterEstimationWidget
from cadetgui.widgets.instrument import DataImportWidget


@pytest.fixture
def simulations(monkeypatch):
    """Count the widget's preview simulations."""
    calls = []

    def counting(process, **kwargs):
        calls.append(process)
        return run_process(process, **kwargs)

    monkeypatch.setattr(estimation_module, "run_process", counting)
    return calls


def edit_flow_rate(configuration, value=5e-6):
    """Commit an edit that rebuilds the configuration's process."""
    configuration._model_form.element("flow_rate").value = value


def reference_series(widget):
    return [s for s in widget._chart.series if s.get("reference")]


def test_binding_lists_parameters_components_signals_and_previews(configuration):
    before = configuration.column_form.collect_values()
    data = DataImportWidget()
    widget = ParameterEstimationWidget(data=data)

    widget.bind_to_config(configuration)

    assert widget.data is data
    assert {p.owner for p in widget.param_space.params} == {"column", "binding"}
    assert len(widget.param_space) == 0
    assert widget._component_picker.option_labels == [
        "Component 1", "Total (sum of all components)",
    ]
    assert widget._component_picker.value == "Component 1"
    assert widget._signal_picker.value == ("outlet", "inlet")
    assert widget._chart.series
    assert configuration.column_form.collect_values() == before


def test_unrelated_configuration_edits_keep_the_user_s_choices(bound, add_param):
    configuration, widget = bound
    index = add_param(widget, "total_porosity")
    space = widget.param_space
    space._start_fields[0].value, space._lb_fields[0].value, space._ub_fields[0].value = (
        0.5, 0.1, 0.9,
    )
    widget._component_picker.value = None
    widget._signal_picker.selected_index = 1
    signal = widget._signal_picker.value

    edit_flow_rate(configuration)

    assert space.rows() == [(index, 0.5, 0.1, 0.9)]
    assert widget._component_picker.value is None
    assert widget._signal_picker.value == signal


def test_a_parameter_added_starts_at_its_current_value_and_can_be_removed(bound, add_param):
    _, widget = bound
    index = add_param(widget, "total_porosity")
    param = widget.param_space.params[index]

    assert widget.param_space.rows() == [(index, param.current_value, param.lb, param.ub)]

    widget.param_space._remove_buttons[0].click()

    assert len(widget.param_space) == 0


def test_preview_simulates_on_configuration_changes_only(bound, simulations, upload):
    configuration, widget = bound
    upload(widget.data, "m.csv", "time,signal\n" + "\n".join(f"{t},{t}" for t in range(10)))

    widget._dataset_picker.selected_index = 0
    widget._calibration_picker.value = "beer_lambert"
    widget._extinction_field.value = 2.0
    configuration.persistence._name_field.value = "Renamed"

    assert simulations == []
    assert len(reference_series(widget)) == 1

    edit_flow_rate(configuration)

    assert len(simulations) == 1


def test_preview_failures_and_a_missing_process_are_reported(bound, monkeypatch):
    configuration, widget = bound

    def fail(process, **kwargs):
        raise RuntimeError("synthetic sim failure")

    monkeypatch.setattr(estimation_module, "run_process", fail)
    edit_flow_rate(configuration)

    assert "synthetic sim failure" in widget._preview_status.value
    assert widget._chart.series == []

    configuration.process = None
    widget._refresh_preview()

    assert "configuration" in widget._preview_status.value.lower()


def test_a_non_time_series_signal_falls_back_to_a_figure(monkeypatch, ready):
    monkeypatch.setattr(estimation_module, "solution_series", lambda *a, **k: None)
    _, widget = ready

    widget._refresh_preview(force=True)

    assert widget._plot_out.value


def test_auto_preview_off_defers_the_simulation_until_shown(bound, simulations):
    configuration, widget = bound
    widget.auto_preview = False

    edit_flow_rate(configuration)
    assert simulations == []

    widget.refresh_preview()
    assert len(simulations) == 1


@pytest.mark.parametrize(
    ("setup", "error"),
    [
        ("no_dataset", "dataset"),
        ("no_parameter", "parameter"),
        ("start_outside_bounds", "bounds"),
        ("beer_lambert_zero", "extinction"),
        ("zero_injected_amount", "injected amount"),
    ],
)
def test_invalid_inputs_are_reported_without_running(
    ready, fake_optimization, synchronous_threads, setup, error
):
    _, widget = ready
    calls = fake_optimization()
    if setup == "no_dataset":
        widget.data.clear()
    elif setup == "no_parameter":
        widget.param_space.clear()
    elif setup == "start_outside_bounds":
        widget.param_space._start_fields[0].value = 2.0
    elif setup == "beer_lambert_zero":
        widget._calibration_picker.value = "beer_lambert"
        widget._extinction_field.value = 0.0
    else:
        widget._calibration_picker.value = "normalize_area"
        widget._target_area_field.value = 0.0

    widget._runner._btn_run.click()

    assert error in widget.status.value.lower()
    assert calls == []


@pytest.mark.parametrize("calibration", ["none", "beer_lambert", "normalize_area"])
def test_run_fits_from_the_start_values_and_accept_writes_them_back(
    ready, fake_optimization, synchronous_threads, calibration
):
    configuration, widget = ready
    widget._calibration_picker.value = calibration
    (index, *_), = widget.param_space.rows()
    widget.param_space._start_fields[0].value = 0.6
    calls = fake_optimization({f"var_{index}": 0.65})
    results = []
    widget.add_listener(results.append)

    widget._runner._btn_run.click()

    assert calls[0]["x0"] == [0.6]
    assert widget.result.fitted == {index: 0.65}
    assert results == [widget.result]
    assert configuration.column_form.collect_values()["total_porosity"] != 0.65

    widget._runner._btn_accept.click()

    assert configuration.column_form.collect_values()["total_porosity"] == pytest.approx(0.65)


def test_accept_writes_one_component_of_a_per_component_parameter(
    bound, upload, csv_of, fake_optimization, synchronous_threads
):
    configuration, widget = bound
    configuration.components = ["A", "B"]
    upload(widget.data, "m.csv", csv_of(widget._display_result.solution.outlet.inlet, column=1))
    widget._dataset_picker.selected_index = 0
    widget._component_picker.value = "B"
    space = widget.param_space
    index = next(
        i for i, p in enumerate(space.params)
        if p.name == "adsorption_rate" and p.component_index == 1
    )
    space._param_add_picker.value = space._param_key(space.params[index])
    space._btn_add_param.click()
    fake_optimization({f"var_{index}": 0.25})

    widget._runner._btn_run.click()
    widget._runner._btn_accept.click()

    assert configuration.binding_form.collect_values()["adsorption_rate"] == [0.0, 0.25]


def test_a_saved_configuration_can_be_picked_as_base_process(bound):
    configuration, widget = bound
    configuration.persistence._name_field.value = "Saved Base"
    assert widget._base_process_picker.option_labels == ["Saved Base (Active)"]
    saved = configuration.config_hash
    configuration.persist_to_store()
    widget._btn_refresh_store.click()
    assert widget._base_process_picker.option_labels == ["Saved Base (Active)", "Saved Base"]

    edit_flow_rate(configuration)
    widget._base_process_picker.selected_index = 1

    assert configuration.config_hash == saved


def test_clear_removes_data_parameters_and_results_unless_running(
    ready, fake_optimization, synchronous_threads, monkeypatch
):
    _, widget = ready
    (index, *_), = widget.param_space.rows()
    fake_optimization({f"var_{index}": 0.65})
    widget._runner._btn_run.click()
    monkeypatch.setattr(type(widget._runner), "running", property(lambda _self: True))

    widget._btn_clear.click()
    assert widget.data.datasets and "Cancel" in widget.status.value

    monkeypatch.undo()
    widget._btn_clear.click()

    assert widget.data.datasets == []
    assert len(widget.param_space) == 0
    assert widget.result is None
    assert widget._runner._fit_table.value == ""


@pytest.mark.slow
@pytest.mark.parametrize("component", [None, "Component 2"])
def test_real_fit_end_to_end(bound, add_param, upload, csv_of, synchronous_threads, component):
    configuration, widget = bound
    configuration.components = ["Component 1", "Component 2"]
    column = None if component is None else 1
    upload(widget.data, "m.csv", csv_of(widget._display_result.solution.outlet.inlet, column))
    widget._dataset_picker.selected_index = 0
    widget._component_picker.value = component
    add_param(widget, "total_porosity")
    widget._runner._knob_fields["Nelder-Mead"][0].value = 20
    widget._runner._show_analytics_checkbox.value = True

    widget._runner._btn_run.click()

    assert widget.result is not None and widget.result.success, widget.status.value
    assert widget._runner._convergence_out.value
    widget._runner._btn_accept.click()
    assert configuration.column_form.collect_values()["total_porosity"] == pytest.approx(
        next(iter(widget.result.fitted.values()))
    )
