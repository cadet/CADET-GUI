from __future__ import annotations

import datetime as dt
import threading
import time
import warnings

import cadetgui.configuration_store as configuration_store
import cadetgui.widgets.composite._optimizer_runner_panel as runner_panel
import ipywidgets as W
import pytest
from cadetgui.optimizer_runner import OptimizerRunResult, RunSpec
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


def test_parameter_estimation_widget_nests_a_data_import_widget():
    pw = ParameterEstimationWidget()

    assert isinstance(pw.data, DataImportWidget)
    # Nested one level deep, inside the "Experimental data" section -- not a
    # direct child of `pw.root` itself.
    nested_children = [
        child for section in pw.root.children for child in getattr(section, "children", ())
    ]
    assert pw.data.root in nested_children


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


def test_config_field_changes_rebuild_the_add_parameter_picker():
    pw = ParameterEstimationWidget()
    cw = built_configuration()
    pw.bind_to_config(cw)
    before = len(pw.param_space._param_add_picker.option_labels)

    cw._model_form.element("flow_rate").value = 5e-6  # any committed change

    assert len(pw.param_space._param_add_picker.option_labels) == before  # rebuilt, no crash


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


def test_preview_is_a_titled_section_without_a_preview_button():
    pw = ParameterEstimationWidget()

    assert not hasattr(pw, "_btn_preview")
    titles = [
        w.value for w in _descendants(pw.root)
        if isinstance(w, W.HTML) and "cadetgui-section-title'>Preview<" in w.value
    ]
    assert len(titles) == 1


def _descendants(widget):
    yield widget
    for child in getattr(widget, "children", ()):
        yield from _descendants(child)


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


def test_starting_a_run_clears_and_hides_every_chart():
    cw, pw = _bound_widgets()
    _ready_to_run(cw, pw)
    pw._runner._live_chart.series = [{"name": "x", "times": [0.0], "values": [1.0]}]
    pw._runner._history_chart.series = [{"name": "x", "times": [1.0], "values": [1.0]}]

    pw._runner._on_run(None)

    # A finished run redraws the final overlay, but the live-only charts stay cleared.
    assert pw._runner._live_chart.series == []
    assert pw._runner._history_chart.series == []


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


def test_signal_options_match_the_ones_the_simulated_preview_offers():
    from cadetgui.cadetprocessadapter import (
        classify_signal_ports,
        measurable_signal_options,
    )

    pw = ParameterEstimationWidget()
    pw.bind_to_config(built_configuration())

    offered = measurable_signal_options(
        pw._display_result.process, classify_signal_ports(pw._display_result)
    )
    assert pw._signal_picker.option_labels == [label for label, _ in offered]


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


def test_run_estimation_succeeds_with_beer_lambert_calibration():
    cw, pw = _bound_widgets()
    _ready_to_run(cw, pw)
    pw._calibration_picker.value = "beer_lambert"
    pw._extinction_field.value = 2.0
    pw._path_length_field.value = 1.0

    pw._runner._on_run(None)

    assert pw._last_result is not None
    assert pw._last_result.success


def test_run_estimation_succeeds_with_area_normalization_calibration():
    cw, pw = _bound_widgets()
    _ready_to_run(cw, pw)
    pw._calibration_picker.value = "normalize_area"
    pw._target_area_field.value = 1.0

    pw._runner._on_run(None)

    assert pw._last_result is not None
    assert pw._last_result.success


def test_run_estimation_passes_the_start_fields_as_starts(monkeypatch):
    cw, pw = _bound_widgets()
    _ready_to_run(cw, pw)
    # Field 0 is always `axial_dispersion` for this default config -- fields
    # are alphabetical now (`build_parameter_config_spec` sorts by name), and
    # it's the config's own seed value (1e-8) offset within its bounds
    # ([0, 1e-7]), not that value itself.
    pw.param_space._start_fields[0].value = 5e-8
    captured = {}

    def _fake_run_optimization(problem, optimizer_name, optimizer_kwargs, x0, **kwargs):
        captured["x0"] = list(x0)
        return OptimizerRunResult({}, None, False, "stopped for the test")

    _stub_optimization(monkeypatch, _fake_run_optimization)

    pw._runner._on_run(None)

    # If `_on_run` ever returns before running the optimization (e.g. a
    # future regression re-introducing param-order instability), surface
    # *why* via the guard-clause message instead of a bare KeyError.
    assert "x0" in captured, (
        f"the optimization was never run; pw.status was: {pw.status.value!r}"
    )
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


def test_elapsed_label_is_cleared_after_a_run_finishes():
    cw, pw = _bound_widgets()
    _ready_to_run(cw, pw)

    pw._runner._on_run(None)

    # Cleared once finished -- the final elapsed time is folded into `status` instead.
    assert pw._runner._elapsed_label.value == ""
    assert "s)" in pw.status.value  # e.g. "... (0s)"


class _FakeResults:
    def __init__(self, n_gen: int, x_best, f_best_history):
        self.populations = [None] * n_gen
        self._x_best = x_best
        self.f_best_history = f_best_history

    @property
    def x(self):
        return [self._x_best]


class _FakeOptimizer:
    def __init__(self, results):
        self.results = results


def _built_run_spec(pw, cw):
    _ready_to_run(cw, pw)
    spec = pw._build_run_spec()
    assert isinstance(spec, RunSpec), spec
    return spec


def _stub_optimization(monkeypatch, fake):
    monkeypatch.setattr(runner_panel, "run_optimization", fake)


def test_progress_tick_skips_the_live_plot_when_the_checkbox_is_off(monkeypatch):
    import cadetgui.widgets.composite.parameter_estimation as pe_widget

    cw, pw = _bound_widgets()
    spec = _built_run_spec(pw, cw)
    calls = []
    monkeypatch.setattr(pe_widget, "simulate_at", lambda *a, **k: calls.append(1))
    pw._runner._progress["optimizer"] = _FakeOptimizer(_FakeResults(1, [0.5], [[1.0]]))
    pw._runner._live_plot_checkbox.value = False

    pw._runner._progress_tick(0.0, spec, 0)

    assert calls == []


def test_progress_tick_redraws_the_live_plot_when_the_checkbox_is_on_and_a_generation_completed(
    monkeypatch,
):
    import cadetgui.widgets.composite.parameter_estimation as pe_widget

    cw, pw = _bound_widgets()
    spec = _built_run_spec(pw, cw)
    calls = []
    monkeypatch.setattr(
        pe_widget, "simulate_at",
        lambda *a, **k: calls.append(1) or pw._display_result,
    )
    pw._runner._progress["optimizer"] = _FakeOptimizer(_FakeResults(1, [0.5], [[1.0]]))
    pw._runner._live_plot_checkbox.value = True

    last_n_gen = pw._runner._progress_tick(0.0, spec, 0)

    assert calls == [1]
    assert last_n_gen == 1
    assert pw._runner._live_chart.layout.display == ""
    assert pw._runner._live_chart.series
    assert pw._runner._history_chart.series[0]["values"] == [1.0]


def test_progress_tick_does_not_redraw_twice_for_the_same_generation(monkeypatch):
    import cadetgui.widgets.composite.parameter_estimation as pe_widget

    cw, pw = _bound_widgets()
    spec = _built_run_spec(pw, cw)
    calls = []
    monkeypatch.setattr(pe_widget, "simulate_at", lambda *a, **k: calls.append(1))
    pw._runner._progress["optimizer"] = _FakeOptimizer(_FakeResults(1, [0.5], [[1.0]]))
    pw._runner._live_plot_checkbox.value = True

    last_n_gen = pw._runner._progress_tick(0.0, spec, 1)

    assert calls == []  # n_gen (1) == last_n_gen (1) -- nothing new since last tick
    assert last_n_gen == 1


def test_redraw_live_plot_shows_the_error_instead_of_staying_silently_blank(monkeypatch):
    # Regression: a bare `except: return` here used to make the live panel
    # stay empty for an entire run with zero indication anything went wrong.
    import cadetgui.widgets.composite.parameter_estimation as pe_widget

    cw, pw = _bound_widgets()
    spec = _built_run_spec(pw, cw)

    def _boom(*a, **k):
        raise RuntimeError("synthetic failure for the test")

    monkeypatch.setattr(pe_widget, "simulate_at", _boom)
    optimizer = _FakeOptimizer(_FakeResults(1, [0.5], [[1.0]]))

    pw._runner._redraw_live_plot(optimizer, spec)

    assert "synthetic failure for the test" in pw._runner._live_plot_error.value


def test_cancel_button_hidden_by_default_and_shown_while_a_fit_is_running(monkeypatch):
    cw, pw = _bound_widgets()
    _ready_to_run(cw, pw)
    seen_display_mid_run = {}

    def _fake_run_optimization(*args, **kwargs):
        seen_display_mid_run["display"] = pw._runner._btn_cancel.layout.display
        return OptimizerRunResult({}, None, False, "stopped for the test")

    _stub_optimization(monkeypatch, _fake_run_optimization)

    assert pw._runner._btn_cancel.layout.display == "none"

    pw._runner._on_run(None)

    assert seen_display_mid_run["display"] == ""  # shown while the (mocked) fit "ran"
    assert pw._runner._btn_cancel.layout.display == "none"  # hidden again once finished


def test_clicking_cancel_sets_the_event_the_optimization_receives(monkeypatch):
    cw, pw = _bound_widgets()
    _ready_to_run(cw, pw)
    captured = {}

    def _fake_run_optimization(*args, **kwargs):
        captured.update(kwargs)
        pw._runner._on_cancel(None)  # simulate the user clicking Cancel mid-run
        return OptimizerRunResult(
            {}, None, False, "Optimization cancelled by user.", cancelled=True
        )

    _stub_optimization(monkeypatch, _fake_run_optimization)

    pw._runner._on_run(None)

    assert captured["cancel_event"] is pw._runner._cancel_event
    assert pw._runner._cancel_event.is_set()


def test_finish_run_shows_a_plain_message_for_a_cancelled_result_not_an_error():
    _, pw = _bound_widgets()
    spec = RunSpec(None, [], lambda *_: None, lambda _: "", lambda _: None)

    pw._runner._finish_run(
        OptimizerRunResult({}, None, False, "Optimization cancelled by user.", cancelled=True),
        start_time=time.monotonic(),
        run_spec=spec,
    )

    assert "cancelled" in pw.status.value.lower()
    assert "cadetgui-msg-error" not in pw.status.value
    assert pw._runner._btn_cancel.layout.display == "none"


def test_optimizer_picker_defaults_to_nelder_mead_and_switching_swaps_knob_boxes():
    pw = ParameterEstimationWidget()

    assert pw._runner._optimizer_picker.value == "Nelder-Mead"
    assert pw._runner._knob_boxes["Nelder-Mead"].layout.display == ""
    assert pw._runner._knob_boxes["U-NSGA-III"].layout.display == "none"

    pw._runner._optimizer_picker.value = "U-NSGA-III"

    assert pw._runner._knob_boxes["Nelder-Mead"].layout.display == "none"
    assert pw._runner._knob_boxes["U-NSGA-III"].layout.display == ""


def test_on_run_passes_the_selected_optimizer_and_its_knob_values(monkeypatch):
    cw, pw = _bound_widgets()
    _ready_to_run(cw, pw)
    pw._runner._optimizer_picker.value = "U-NSGA-III"
    pop_size_field, n_max_gen_field = pw._runner._knob_fields["U-NSGA-III"]
    pop_size_field.value = 24
    n_max_gen_field.value = 7
    captured = {}

    def _fake_run_optimization(problem, optimizer_name, optimizer_kwargs, x0, **kwargs):
        captured["optimizer_name"] = optimizer_name
        captured["optimizer_kwargs"] = dict(optimizer_kwargs)
        return OptimizerRunResult({}, None, False, "stopped for the test")

    _stub_optimization(monkeypatch, _fake_run_optimization)

    pw._runner._on_run(None)

    assert captured["optimizer_name"] == "U-NSGA-III"
    assert captured["optimizer_kwargs"] == {"pop_size": 24, "n_max_gen": 7}


def test_cancel_description_mentions_generation_for_a_population_based_optimizer():
    _, pw = _bound_widgets()

    pw._runner._optimizer_picker.value = "U-NSGA-III"
    pw._runner._on_cancel(None)
    assert "generation" in pw._runner._btn_cancel.description.lower()

    pw._runner._btn_cancel.disabled = False
    pw._runner._optimizer_picker.value = "Nelder-Mead"
    pw._runner._on_cancel(None)
    assert "generation" not in pw._runner._btn_cancel.description.lower()


class _FakeAnalyticsResults:
    def __init__(self, n_gen: int, n_var: int):
        self.populations = [None] * n_gen
        self._n_var = n_var

    def plot_convergence(self, ax):
        ax[0].plot([1, 2, 3])

    def plot_pairwise(self, ax):
        pass

    @property
    def x(self):
        return [[0.0] * self._n_var]


def _analytics_widgets():
    cw, pw = _bound_widgets()
    pw._runner._show_analytics_checkbox.value = True
    return cw, pw


def test_convergence_section_and_setting_are_hidden_by_default():
    _, pw = _bound_widgets()

    assert pw._runner._show_analytics_checkbox.value is False
    assert pw._runner._analytics_box.layout.display == "none"
    assert pw._runner._analytics_settings.box.layout.display == "none"
    assert pw._runner._show_analytics_checkbox.description == "Show convergence & correlation"


def test_the_settings_checkbox_shows_and_hides_the_convergence_section():
    _, pw = _bound_widgets()

    pw._runner._show_analytics_checkbox.value = True
    assert pw._runner._analytics_box.layout.display == ""

    pw._runner._show_analytics_checkbox.value = False
    assert pw._runner._analytics_box.layout.display == "none"


def test_render_analytics_does_no_work_while_the_section_is_off():
    _, pw = _bound_widgets()
    optimizer = type("Opt", (), {"results": _FakeAnalyticsResults(3, 1)})()

    pw._runner._render_analytics(optimizer)

    assert pw._runner._convergence_out.value == b""
    assert pw._runner._convergence_out.layout.display == "none"


def test_enabling_the_section_after_a_run_renders_the_last_run():
    _, pw = _bound_widgets()
    pw._runner._progress["optimizer"] = type("Opt", (), {"results": _FakeAnalyticsResults(3, 1)})()

    pw._runner._show_analytics_checkbox.value = True

    assert pw._runner._convergence_out.layout.display == ""
    assert pw._runner._convergence_out.value


def test_render_analytics_shows_convergence_and_hides_pairwise_for_one_parameter():
    _, pw = _analytics_widgets()
    optimizer = type("Opt", (), {"results": _FakeAnalyticsResults(3, 1)})()

    pw._runner._render_analytics(optimizer)

    assert pw._runner._convergence_out.layout.display == ""
    assert pw._runner._convergence_out.value
    assert pw._runner._pairwise_out.layout.display == "none"  # 1 variable -- degenerate, skipped
    assert pw._runner._analytics_error.value == ""


def test_render_analytics_shows_pairwise_for_two_parameters():
    _, pw = _analytics_widgets()
    optimizer = type("Opt", (), {"results": _FakeAnalyticsResults(3, 2)})()

    pw._runner._render_analytics(optimizer)

    assert pw._runner._pairwise_out.layout.display == ""
    assert pw._runner._pairwise_out.value


def test_render_analytics_skips_silently_before_the_first_generation():
    _, pw = _analytics_widgets()
    optimizer = type("Opt", (), {"results": _FakeAnalyticsResults(0, 1)})()

    pw._runner._render_analytics(optimizer)

    assert pw._runner._convergence_out.layout.display == "none"
    assert pw._runner._convergence_out.value == b""


def test_render_analytics_surfaces_errors_instead_of_staying_silent():
    _, pw = _analytics_widgets()

    class _BoomResults(_FakeAnalyticsResults):
        def plot_convergence(self, ax):
            raise RuntimeError("synthetic analytics failure")

    optimizer = type("Opt", (), {"results": _BoomResults(2, 1)})()

    pw._runner._render_analytics(optimizer)

    assert "synthetic analytics failure" in pw._runner._analytics_error.value


@pytest.mark.slow
def test_finish_run_renders_analytics_after_a_real_run():
    cw, pw = _analytics_widgets()
    _ready_to_run(cw, pw)

    pw._runner._on_run(None)

    assert pw._last_result is not None
    assert pw._last_result.success
    assert pw._runner._convergence_out.layout.display == ""
    assert pw._runner._convergence_out.value
