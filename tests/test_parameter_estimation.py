from __future__ import annotations

import datetime as dt
import threading
import warnings

import cadetgui.io.configuration_store as configuration_store
import cadetgui.widgets.composite._optimizer_runner_panel as runner_panel
import pytest
from cadetgui.optimizer_runner import OptimizerRunResult
from cadetgui.simulation import run_process
from cadetgui.widgets.composite import (
    ConfigurationWidget,
    DataImportWidget,
    InstrumentWidget,
    ParameterEstimationWidget,
)

warnings.filterwarnings("ignore", category=UserWarning)


def built_configuration() -> ConfigurationWidget:
    """A default InstrumentWidget + bound ConfigurationWidget, auto-committed."""
    iw = InstrumentWidget()
    return ConfigurationWidget(instrument=iw)


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Redirect the configuration store to a tmp dir -- never touch the real one."""
    monkeypatch.setattr(configuration_store, "default_store_dir", lambda: tmp_path)


@pytest.fixture(autouse=True)
def _synchronous_threads(monkeypatch):
    """Make `_on_run`'s background threads run synchronously and in order.

    `_on_run` starts a worker thread (runs the fit, sets `_run_done`) and a
    ticker thread (waits on `_run_done`, then finalizes the UI) -- starting
    the worker first means, with `start()` running its target inline, the
    worker completes (and sets `_run_done`) before the ticker "starts," so
    the ticker's wait-loop exits on its very first check with zero real
    iterations. Net effect: `pw._runner._on_run(None)` behaves fully synchronously,
    exactly like the pre-threading version -- no sleeps, no flakiness.
    """
    monkeypatch.setattr(threading.Thread, "start", lambda self: self.run())


def upload_csv(widget: DataImportWidget, filename: str, csv_text: str) -> None:
    content = memoryview(csv_text.encode("utf-8"))
    widget._upload.value = (
        {
            "name": filename,
            "type": "text/csv",
            "size": len(content),
            "last_modified": dt.datetime.now(),
            "content": content,
        },
    )


def _add_param(pw: ParameterEstimationWidget, index: int) -> None:
    """Add `pw.param_space.params[index]` to the fit via the real Add-parameter flow."""
    key = pw.param_space._param_key(pw.param_space.params[index])
    pw.param_space._param_add_picker.value = key
    pw.param_space._on_add_param(None)


def test_parameter_estimation_widget_accepts_a_prebuilt_data_widget():
    dw = DataImportWidget()
    pw = ParameterEstimationWidget(data=dw)

    assert pw.data is dw


def test_bind_to_config_populates_the_add_parameter_picker():
    pw = ParameterEstimationWidget()
    cw = built_configuration()

    pw.bind_to_config(cw)

    assert len(pw.param_space.params) > 0
    assert len(pw.param_space._param_add_picker.option_labels) == len(pw.param_space.params)
    assert pw.param_space._added_keys == []  # nothing added by default


def test_adding_a_parameter_removes_it_from_the_add_picker_and_adds_a_row():
    pw = ParameterEstimationWidget()
    cw = built_configuration()
    pw.bind_to_config(cw)
    before = len(pw.param_space._param_add_picker.option_labels)

    _add_param(pw, 0)

    assert pw.param_space._added_keys == [pw.param_space._param_key(pw.param_space.params[0])]
    assert len(pw.param_space._param_box.children) == 1
    assert len(pw.param_space._param_add_picker.option_labels) == before - 1


def test_removing_a_parameter_puts_it_back_in_the_add_picker():
    pw = ParameterEstimationWidget()
    cw = built_configuration()
    pw.bind_to_config(cw)
    _add_param(pw, 0)
    before = len(pw.param_space._param_add_picker.option_labels)

    pw.param_space._remove_buttons[0].click()

    assert pw.param_space._added_keys == []
    assert len(pw.param_space._param_box.children) == 0
    assert len(pw.param_space._param_add_picker.option_labels) == before + 1


def test_unrelated_config_edits_preserve_edited_start_lb_ub_for_an_added_parameter():
    pw = ParameterEstimationWidget()
    cw = built_configuration()
    pw.bind_to_config(cw)
    _add_param(pw, 0)
    pw.param_space._start_fields[0].value = 0.123
    pw.param_space._lb_fields[0].value = 0.01
    pw.param_space._ub_fields[0].value = 0.99

    cw._model_form.element("flow_rate").value = 5e-6  # unrelated committed change

    assert len(pw.param_space._added_keys) == 1  # still added
    assert pw.param_space._start_fields[0].value == 0.123
    assert pw.param_space._lb_fields[0].value == 0.01
    assert pw.param_space._ub_fields[0].value == 0.99


def test_start_field_defaults_to_the_current_config_value_for_a_new_parameter():
    pw = ParameterEstimationWidget()
    cw = built_configuration()
    pw.bind_to_config(cw)

    _add_param(pw, 0)

    assert pw.param_space._start_fields[0].value == pw.param_space.params[0].current_value


def test_bind_to_config_populates_the_component_picker_with_components_and_total():
    pw = ParameterEstimationWidget()
    cw = built_configuration()

    pw.bind_to_config(cw)

    assert pw._component_picker.option_labels == [
        "Component 1", "Total (sum of all components)",
    ]
    assert pw._component_picker.value == "Component 1"  # a real component, not Total


def test_unrelated_config_edits_do_not_reset_an_explicit_total_pick():
    pw = ParameterEstimationWidget()
    cw = built_configuration()
    pw.bind_to_config(cw)
    pw._component_picker.value = None  # "Total (sum of all components)"

    cw._model_form.element("flow_rate").value = 5e-6  # unrelated committed change

    assert pw._component_picker.value is None  # still "Total", not bounced to index 0


def test_bind_to_config_populates_the_base_process_picker_with_the_active_configuration_only():
    pw = ParameterEstimationWidget()
    cw = built_configuration()
    cw.config_name = "My Config"

    pw.bind_to_config(cw)

    assert pw._base_process_picker.option_labels == ["My Config (Active)"]
    assert pw._base_process_picker.value is None


def test_base_process_label_falls_back_when_no_configuration_is_bound_or_unnamed():
    pw = ParameterEstimationWidget()
    assert pw._base_process_picker.option_labels == ["Current configuration (Active)"]

    cw = built_configuration()
    cw.persistence._name_field.value = ""
    pw.bind_to_config(cw)

    assert pw._base_process_picker.option_labels == ["Current configuration (Active)"]


def test_base_process_label_follows_a_configuration_rename():
    pw = ParameterEstimationWidget()
    cw = built_configuration()
    pw.bind_to_config(cw)

    cw.persistence._name_field.value = "Renamed"

    assert pw._base_process_picker.option_labels == ["Renamed (Active)"]
    assert pw._base_process_picker.value is None


def test_binding_previews_automatically_without_touching_the_configuration():
    cw = built_configuration()
    before = cw._column_form.collect_values()
    pw = ParameterEstimationWidget()

    pw.bind_to_config(cw)

    assert pw._display_result is not None
    assert pw._signal_picker.option_labels
    assert cw._column_form.collect_values() == before


def test_preview_section_chart_is_shown_once_the_overlay_is_drawn():
    pw = ParameterEstimationWidget()
    assert pw._chart.layout.display == "none"

    pw.bind_to_config(built_configuration())

    assert pw._chart.layout.display == ""
    assert pw._chart.series
    assert pw._plot_out.layout.display == "none"  # matplotlib fallback stays unused
    assert pw._preview_status.value == ""


def _small_measurement() -> str:
    return "time,signal\n" + "\n".join(f"{t},{t * 0.1}" for t in range(10))


def _count_simulations(monkeypatch) -> list[int]:
    import cadetgui.widgets.composite.parameter_estimation as pe_widget

    calls: list[int] = []

    def counting(process, **kwargs):
        calls.append(1)
        return run_process(process, **kwargs)

    monkeypatch.setattr(pe_widget, "run_process", counting)
    return calls


def test_changing_the_configuration_refreshes_the_preview(monkeypatch):
    calls = _count_simulations(monkeypatch)
    cw, pw = _bound_widgets()
    before = pw._chart.series
    n = len(calls)

    cw._model_form.element("flow_rate").value = 9.9e-6

    assert len(calls) > n
    assert pw._chart.series != before


def test_nothing_relevant_changed_means_no_new_simulation(monkeypatch):
    calls = _count_simulations(monkeypatch)
    cw, pw = _bound_widgets()
    upload_csv(pw.data, "m.csv", _small_measurement())
    n = len(calls)

    pw._refresh_preview()
    cw.persistence._name_field.value = "Renamed"
    pw._signal_picker.selected_index = 1
    pw._calibration_picker.value = "beer_lambert"
    pw._extinction_field.value = 2.0
    pw._dataset_picker.selected_index = 0

    assert len(calls) == n


def test_dataset_change_updates_the_overlay_without_simulating(monkeypatch):
    calls = _count_simulations(monkeypatch)
    _, pw = _bound_widgets()
    n = len(calls)
    assert not [s for s in pw._chart.series if s.get("reference")]

    upload_csv(pw.data, "m.csv", _small_measurement())
    pw._dataset_picker.selected_index = 0

    assert [s for s in pw._chart.series if s.get("reference")]
    assert len(calls) == n


def test_a_failing_preview_simulation_shows_an_error_instead_of_crashing(monkeypatch):
    import cadetgui.widgets.composite.parameter_estimation as pe_widget

    cw, pw = _bound_widgets()

    def boom(process, **kwargs):
        raise RuntimeError("synthetic sim failure")

    monkeypatch.setattr(pe_widget, "run_process", boom)
    cw._model_form.element("flow_rate").value = 9.9e-6

    assert "synthetic sim failure" in pw._preview_status.value
    assert "cadetgui-msg-error" in pw._preview_status.value
    assert pw._display_result is None
    assert pw._chart.layout.display == "none"


def test_the_preview_shows_a_running_status_while_simulating(monkeypatch):
    import cadetgui.widgets.composite.parameter_estimation as pe_widget

    cw, pw = _bound_widgets()
    seen: list[str] = []

    def spying(process, **kwargs):
        seen.append(pw._preview_status.value)
        return run_process(process, **kwargs)

    monkeypatch.setattr(pe_widget, "run_process", spying)
    cw._model_form.element("flow_rate").value = 9.9e-6

    assert "cadetgui-spinner" in seen[0]


def test_overlay_adds_the_measured_dataset_as_a_dashed_reference_series():
    cw, pw = _bound_widgets()
    _ready_to_run(cw, pw)

    pw._redraw_overlay()

    measured = [s for s in pw._chart.series if s.get("reference")]
    assert len(measured) == 1
    assert measured[0]["dashed"] is True
    assert measured[0]["name"] == "measured (measured)"
    assert len(pw._chart.series) == len(measured) + len(cw.process.component_system.names)


def test_overlay_falls_back_to_the_matplotlib_plot_for_non_time_series_signals(monkeypatch):
    import cadetgui.widgets.composite.parameter_estimation as pe_widget

    monkeypatch.setattr(pe_widget, "solution_series", lambda *_a, **_k: None)
    pw = ParameterEstimationWidget()
    pw.bind_to_config(built_configuration())

    assert pw._chart.layout.display == "none"
    assert pw._plot_out.layout.display == ""
    assert pw._plot_out.value  # actual PNG bytes


def test_signal_picker_is_populated_on_bind_and_defaults_to_the_sink():
    pw = ParameterEstimationWidget()
    cw = built_configuration()
    pw.bind_to_config(cw)

    assert pw._signal_picker.option_labels[0] == "Outlet"
    assert pw._signal_picker.value == ("outlet", "inlet")


def test_signal_picker_offers_only_measurable_positions_with_plain_names():
    pw = ParameterEstimationWidget()
    pw.bind_to_config(built_configuration())

    labels = pw._signal_picker.option_labels

    assert "Column outlet" in labels
    assert "Column inlet" in labels
    assert "Feed inlet" in labels  # the inlet this process drives
    idle = ("Buffer A", "Buffer B", "Buffer C", "Buffer D")
    assert not any(label.startswith(idle) for label in labels)
    assert not any(label.startswith(("Mixer", "Sample loop")) for label in labels)
    assert not any(label.endswith(" volume") for label in labels)
    assert not any(": " in label for label in labels)


def test_signal_options_refresh_when_the_configuration_changes():
    pw = ParameterEstimationWidget()
    cw = built_configuration()
    pw.bind_to_config(cw)
    pw._signal_picker.selected_index = 1
    picked = pw._signal_picker.value

    cw._model_form.element("flow_rate").value = 9.9e-6
    assert pw._signal_picker.value == picked  # kept across unrelated edits

    pw._signal_picker.set_options([("stale", ("nope", "inlet"))])
    cw._model_form.element("flow_rate").value = 8.8e-6
    assert pw._signal_picker.option_labels[0] == "Outlet"


def test_preview_without_a_process_shows_a_guard_error():
    cw, pw = _bound_widgets()
    cw.process = None

    pw._refresh_preview()

    assert "configuration" in pw._preview_status.value.lower()
    assert pw._chart.layout.display == "none"


def test_uploading_a_dataset_populates_the_dataset_picker():
    pw = ParameterEstimationWidget()

    upload_csv(pw.data, "run1.csv", "time,signal\n0,0.0\n1,0.5\n2,1.0\n")

    assert pw._dataset_picker.option_labels == ["run1"]


def test_saving_a_configuration_and_refreshing_lists_it_as_a_base_process():
    pw = ParameterEstimationWidget()
    cw = built_configuration()
    pw.bind_to_config(cw)
    cw.persistence._name_field.value = "Saved Base"
    cw.persist_to_store()

    pw._refresh_store_options()

    assert pw._base_process_picker.option_labels == ["Saved Base (Active)", "Saved Base"]


def test_picking_a_saved_base_process_loads_it_into_the_configuration_and_previews():
    pw = ParameterEstimationWidget()
    cw = built_configuration()
    pw.bind_to_config(cw)
    cw.persistence._name_field.value = "Saved Base"
    saved_hash = cw.config_hash
    cw.persist_to_store()
    pw._refresh_store_options()

    cw._model_form.element("flow_rate").value = 9.9e-6  # diverge from the saved snapshot
    assert cw.config_hash != saved_hash

    pw._base_process_picker.selected_index = 1  # "Saved Base"

    assert cw.config_hash == saved_hash  # reloaded via ConfigurationWidget.import_from_store
    assert pw._signal_picker.option_labels  # auto-previewed


def _bound_widgets():
    cw = built_configuration()
    pw = ParameterEstimationWidget()
    pw.bind_to_config(cw)
    return cw, pw


def _uploaded_measurement_from(result, unit: str, port: str) -> str:
    sol = result.solution[unit][port]
    total = sol.solution.sum(axis=1)
    lines = ["time,signal"] + [
        f"{t / 60.0},{s * 1.05}" for t, s in zip(sol.time[::10], total[::10])
    ]
    return "\n".join(lines)


def _set_maxiter(pw: ParameterEstimationWidget, value: int) -> None:
    """Set Nelder-Mead's one knob field ("Max iterations") -- keeps tests fast."""
    pw._runner._knob_fields["Nelder-Mead"][0].value = value


def _ready_to_run(cw, pw):
    unit, port = pw._signal_picker.value
    upload_csv(pw.data, "measured.csv", _uploaded_measurement_from(pw._display_result, unit, port))
    pw._dataset_picker.selected_index = 0
    pw._signal_picker.value = (unit, port)
    _add_param(pw, 0)
    _set_maxiter(pw, 20)


def test_run_estimation_without_a_dataset_shows_a_guard_error():
    _, pw = _bound_widgets()  # signal available, but no dataset imported

    pw._runner._on_run(None)

    assert "dataset" in pw.status.value.lower()


def test_run_estimation_without_a_drawn_preview_works():
    cw, pw = _bound_widgets()
    unit, port = pw._signal_picker.value
    measured = _uploaded_measurement_from(run_process(cw.process), unit, port)
    upload_csv(pw.data, "measured.csv", measured)
    pw._dataset_picker.selected_index = 0
    _add_param(pw, 0)
    _set_maxiter(pw, 20)
    pw._display_result = None

    pw._runner._on_run(None)

    assert pw._last_result is not None
    assert pw._last_result.success


def test_redraw_overlay_without_a_preview_does_not_crash():
    pw = ParameterEstimationWidget()

    pw._redraw_overlay()

    assert pw._chart.series == []


def test_run_estimation_without_an_added_parameter_shows_a_guard_error():
    cw, pw = _bound_widgets()
    upload_csv(pw.data, "run1.csv", "time,signal\n0,0.0\n1,0.5\n2,1.0\n")
    pw._dataset_picker.selected_index = 0
    pw._signal_picker.selected_index = 0

    pw._runner._on_run(None)  # nothing added

    assert "parameter" in pw.status.value.lower()


def test_run_estimation_with_a_start_value_outside_its_bounds_shows_a_guard_error():
    cw, pw = _bound_widgets()
    _ready_to_run(cw, pw)
    pw.param_space._lb_fields[0].value = 0.0
    pw.param_space._ub_fields[0].value = 1e-5
    pw.param_space._start_fields[0].value = 1.0000001  # far outside [0, 1e-5]

    pw._runner._on_run(None)

    assert "bounds" in pw.status.value.lower()
    assert pw._last_result is None


def test_run_estimation_end_to_end_populates_results_and_accept_is_hidden_before_run():
    cw, pw = _bound_widgets()
    _ready_to_run(cw, pw)

    assert pw._runner._btn_accept.layout.display == "none"

    pw._runner._on_run(None)

    assert pw._last_result is not None
    assert pw._last_result.success
    assert pw._runner._btn_accept.layout.display == ""
    assert "Objective" in pw.status.value
    assert pw._chart.layout.display == ""  # final overlay shown
    assert pw._chart.series


def test_accept_writes_fitted_values_into_the_live_configuration_only_on_click():
    cw, pw = _bound_widgets()
    _ready_to_run(cw, pw)

    before = cw._column_form.collect_values()
    pw._runner._on_run(None)
    assert cw._column_form.collect_values() == before  # untouched until Accept

    pw._runner._on_accept(None)

    fitted_name = pw.param_space.params[0].name  # index 0 is always a scalar column field
    assert cw._column_form.collect_values()[fitted_name] == pytest.approx(
        pw._last_result.fitted[0]
    )


def test_picking_a_calibration_method_shows_only_its_own_fields():
    pw = ParameterEstimationWidget()

    assert pw._beer_lambert_box.layout.display == "none"
    assert pw._normalize_area_box.layout.display == "none"

    pw._calibration_picker.value = "beer_lambert"
    assert pw._beer_lambert_box.layout.display == ""
    assert pw._normalize_area_box.layout.display == "none"

    pw._calibration_picker.value = "normalize_area"
    assert pw._beer_lambert_box.layout.display == "none"
    assert pw._normalize_area_box.layout.display == ""

    pw._calibration_picker.value = "none"
    assert pw._beer_lambert_box.layout.display == "none"
    assert pw._normalize_area_box.layout.display == "none"


def test_run_estimation_rejects_a_non_positive_beer_lambert_input():
    cw, pw = _bound_widgets()
    _ready_to_run(cw, pw)
    pw._calibration_picker.value = "beer_lambert"
    pw._extinction_field.value = 0.0

    pw._runner._on_run(None)

    assert "extinction" in pw.status.value.lower()
    assert pw._last_result is None


def test_run_estimation_rejects_a_zero_target_area():
    cw, pw = _bound_widgets()
    _ready_to_run(cw, pw)
    pw._calibration_picker.value = "normalize_area"
    pw._target_area_field.value = 0.0

    pw._runner._on_run(None)

    assert "amount" in pw.status.value.lower()
    assert pw._last_result is None


@pytest.mark.parametrize(
    ("method", "fields"),
    [
        ("beer_lambert", {"_extinction_field": 2.0, "_path_length_field": 1.0}),
        ("normalize_area", {"_target_area_field": 1.0}),
    ],
)
def test_run_estimation_succeeds_with_a_calibration_method(method, fields):
    cw, pw = _bound_widgets()
    _ready_to_run(cw, pw)
    pw._calibration_picker.value = method
    for name, value in fields.items():
        getattr(pw, name).value = value

    pw._runner._on_run(None)

    assert pw._last_result is not None
    assert pw._last_result.success


def test_run_estimation_passes_the_start_fields_as_starts(monkeypatch):
    cw, pw = _bound_widgets()
    _ready_to_run(cw, pw)
    pw.param_space._start_fields[0].value = 5e-8
    captured = {}

    def _fake_run_optimization(problem, optimizer_name, optimizer_kwargs, x0, **kwargs):
        captured["x0"] = list(x0)
        return OptimizerRunResult({}, None, False, "stopped for the test")

    _stub_optimization(monkeypatch, _fake_run_optimization)

    pw._runner._on_run(None)

    assert "x0" in captured, pw.status.value
    assert captured["x0"] == [5e-8]


def test_run_estimation_with_total_selected_still_succeeds():
    cw, pw = _bound_widgets()
    _ready_to_run(cw, pw)
    pw._component_picker.value = None  # "Total (sum of all components)"

    pw._runner._on_run(None)

    assert pw._last_result is not None
    assert pw._last_result.success


def test_run_estimation_with_a_specific_component_selected_succeeds():
    cw, pw = _bound_widgets()
    cw.components = ["Component 1", "Component 2"]  # needs a real 2nd component
    unit, port = pw._signal_picker.value
    sol = pw._display_result.solution[unit][port]
    comp2 = sol.solution[:, 1]
    lines = ["time,signal"] + [
        f"{t / 60.0},{s * 1.05}" for t, s in zip(sol.time[::10], comp2[::10])
    ]
    upload_csv(pw.data, "measured.csv", "\n".join(lines))
    pw._dataset_picker.selected_index = 0
    pw._signal_picker.value = (unit, port)
    pw._component_picker.value = "Component 2"
    _add_param(pw, 0)
    _set_maxiter(pw, 15)

    pw._runner._on_run(None)

    assert pw._last_result is not None
    assert pw._last_result.success


def _stub_optimization(monkeypatch, fake):
    monkeypatch.setattr(runner_panel, "run_optimization", fake)


@pytest.mark.slow
def test_finish_run_renders_analytics_after_a_real_run():
    cw, pw = _bound_widgets()
    pw._runner._show_analytics_checkbox.value = True
    _ready_to_run(cw, pw)

    pw._runner._on_run(None)

    assert pw._last_result is not None
    assert pw._last_result.success
    assert pw._runner._convergence_out.layout.display == ""
    assert pw._runner._convergence_out.value
