from __future__ import annotations

import datetime as dt
import warnings

import cadetgui.configuration_store as configuration_store
import pytest
from cadetgui.widgets.composite import ConfigurationWidget, InstrumentWidget

warnings.filterwarnings("ignore", category=UserWarning)


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Redirect the configuration store to a tmp dir -- never touch the real one."""
    monkeypatch.setattr(configuration_store, "default_store_dir", lambda: tmp_path)


def built():
    """A default InstrumentWidget + bound ConfigurationWidget pair."""
    iw = InstrumentWidget()
    cw = ConfigurationWidget(instrument=iw)
    return iw, cw


def test_configuration_widget_renders_default_forms():
    iw, cw = built()
    assert cw._column_picker.option_labels == [
        "General Rate Model (GRM)",
        "Lumped Rate Model With Pores (LRMP)",
        "Lumped Rate Model Without Pores (LRM)",
    ]
    assert len(cw._column_form_box.children) == 1
    assert len(cw._model_form_box.children) == 1


def test_configuration_widget_builds_process_automatically_with_defaults():
    _, cw = built()

    assert cw.process is not None
    assert type(cw.process).__name__ == "Breakthrough"


def test_configuration_widget_notifies_listeners_on_a_valid_field_change():
    _, cw = built()
    seen = []
    cw.add_listener(seen.append)

    cw._model_form.element("flow_rate").value = 2e-6

    assert len(seen) == 1
    assert seen[0] is cw.process


def test_configuration_widget_rebuilds_forms_on_model_change():
    _, cw = built()
    first_title = cw._model_form.spec.title

    cw._model_picker.selected_index = 1
    assert cw._model_form.spec.title != first_title
    assert len(cw._model_form_box.children) == 1


def test_configuration_widget_rebuilds_column_on_component_change():
    iw, cw = built()
    original_column = cw._get_column()
    assert original_column.n_comp == 1  # Pulse Injection stays single-component-friendly

    cw.components = ["Salt", "Protein", "Impurity"]
    new_column = cw._get_column()
    assert new_column is not original_column
    assert new_column.n_comp == 3
    assert list(new_column.component_system.names) == ["Salt", "Protein", "Impurity"]


def test_export_script_raises_when_nothing_has_been_built():
    # With auto-commit, this state isn't reachable through the default
    # registries (their defaults always build successfully) -- force it
    # directly to keep the guard clause itself covered.
    _, cw = built()
    cw.process = None
    cw._column_form = None
    cw._binding_form = None
    cw._model_form = None
    try:
        cw.export_script()
        assert False, "should have raised"
    except RuntimeError as exc:
        assert "nothing built" in str(exc).lower()


def test_export_script_button_shows_error_status_when_nothing_has_been_built():
    _, cw = built()
    cw.process = None
    cw._column_form = None
    cw._binding_form = None
    cw._model_form = None
    cw._on_export(None)
    assert "nothing built" in cw.status.value.lower()
    assert cw._script_out.layout.display == "none"


def test_export_script_produces_executable_equivalent_process():
    import numpy as np

    iw, cw = built()

    script = cw.export_script()
    ns = {}
    exec(compile(script, "<generated>", "exec"), ns)  # noqa: S102

    assert type(ns["process"]) is type(cw.process)
    assert type(ns["flow_sheet"].column) is type(cw._get_column())
    assert ns["component_system"].n_comp == len(cw.components)
    assert list(ns["component_system"].names) == cw.components

    from cadetgui.simulation import run_process

    res_widget = run_process(cw.process)
    res_script = run_process(ns["process"])
    unit = next(iter(res_widget.solution))
    assert np.array_equal(
        res_widget.solution[unit]["outlet"].solution,
        res_script.solution[unit]["outlet"].solution,
    )


def test_export_script_button_populates_textarea_on_success():
    _, cw = built()

    cw._on_export(None)
    assert "process = " in cw._script_out.value
    assert cw._script_out.layout.display == ""
    assert "generated" in cw.status.value.lower()


def test_binding_model_defaults_to_linear():
    iw, cw = built()
    assert cw._binding_picker.option_labels[0] == "None"  # still first in the dropdown list
    selected = cw._binding_picker.option_labels[cw._binding_picker.selected_index]
    assert selected == "Linear"
    names = {f.name for f in cw._binding_form.spec.fields}
    assert names == {"adsorption_rate", "desorption_rate", "is_kinetic"}


def test_switching_binding_model_rebuilds_its_form():
    iw, cw = built()
    cw._binding_picker.value = cw._binding_registry["Langmuir"]
    assert {f.name for f in cw._binding_form.spec.fields} == {
        "adsorption_rate",
        "desorption_rate",
        "capacity",
        "is_kinetic",
    }


def test_selecting_binding_model_attaches_it_to_the_column():
    iw, cw = built()
    cw._binding_picker.value = cw._binding_registry["Linear"]

    column = cw._get_column()
    assert type(column.binding_model).__name__ == "Linear"


def test_switching_column_type_keeps_binding_model_attachable():
    """Regression test: binding model and column must share one ComponentSystem
    instance (CADET-Process rejects a mismatch) -- LCFlowSheet gives each a
    fresh, shared ComponentSystem on every rebuild."""
    iw, cw = built()
    cw._binding_picker.value = cw._binding_registry["Linear"]

    # different column, different ComponentSystem
    cw._column_picker.value = cw._columns["Lumped Rate Model With Pores (LRMP)"]

    assert cw._binding_form.built is not None
    assert cw._binding_form.status.value == ""
    column = cw._get_column()
    assert type(column.binding_model).__name__ == "Linear"
    assert column.binding_model.component_system is column.component_system


def test_export_script_includes_binding_model_and_round_trips():
    import numpy as np
    from cadetgui.simulation import run_process

    iw, cw = built()
    cw._binding_picker.value = cw._binding_registry["Linear"]

    script = cw.export_script()
    assert "BindingModel=Linear" in script
    assert "flow_sheet.column.binding_model." in script

    ns = {}
    exec(compile(script, "<generated>", "exec"), ns)  # noqa: S102
    assert type(ns["flow_sheet"].column.binding_model).__name__ == "Linear"

    res_widget = run_process(cw.process)
    res_script = run_process(ns["process"])
    unit = next(iter(res_widget.solution))
    assert np.array_equal(
        res_widget.solution[unit]["outlet"].solution,
        res_script.solution[unit]["outlet"].solution,
    )


def test_components_field_defaults_to_one_named_component():
    # The default template stays single-component-friendly.
    iw, cw = built()
    assert cw.components == ["Component 1"]
    assert cw._get_column().n_comp == 1
    assert list(cw._get_column().component_system.names) == ["Component 1"]


def test_component_minimum_and_note_match_the_selected_template():
    iw, cw = built()  # defaults to Breakthrough
    assert cw._components.min_components == 1
    assert cw._component_note.layout.display == "none"

    cw._model_picker.value = cw._registry["Load–Wash–Elute (LWE)"]
    assert cw._components.min_components == 2
    assert cw._component_note.layout.display == ""
    assert "2 components" in cw._component_note.value

    cw._model_picker.value = cw._registry["Step"]
    assert cw._components.min_components == 1
    assert cw._component_note.layout.display == "none"


def test_renaming_components_rebuilds_column_with_new_names():
    iw, cw = built()
    cw.components = ["Salt", "Protein"]

    column = cw._get_column()
    assert column.n_comp == 2
    assert list(column.component_system.names) == ["Salt", "Protein"]


def test_binding_model_scales_to_multiple_named_components():
    iw, cw = built()
    cw.components = ["Salt", "Protein"]
    cw._binding_picker.value = cw._binding_registry["Linear"]

    column = cw._get_column()
    assert column.binding_model.n_comp == 2
    assert cw._binding_form.status.value == ""


def test_binding_form_fields_get_component_names_matching_component_system():
    iw, cw = built()
    cw.components = ["Salt", "Protein"]
    cw._binding_picker.value = cw._binding_registry["Linear"]

    by_name = {f.name: f for f in cw._binding_form.spec.fields}
    assert by_name["adsorption_rate"].component_names == ("Salt", "Protein")
    assert by_name["desorption_rate"].component_names == ("Salt", "Protein")


def test_binding_form_exposes_is_kinetic_defaulting_to_true():
    iw, cw = built()
    cw._binding_picker.value = cw._binding_registry["Linear"]

    element = cw._binding_form.element("is_kinetic")
    assert element.value is True  # CADET-Process's own default
    assert cw._get_column().binding_model.is_kinetic is True


def test_unchecking_is_kinetic_commits_to_the_real_binding_model():
    iw, cw = built()
    cw._binding_picker.value = cw._binding_registry["Langmuir"]

    cw._binding_form.element("is_kinetic").value = False

    assert cw._get_column().binding_model.is_kinetic is False


def test_no_binding_does_not_get_an_is_kinetic_field():
    iw, cw = built()
    cw._binding_picker.value = cw._binding_registry["None"]
    assert "is_kinetic" not in {f.name for f in cw._binding_form.spec.fields}


def test_column_geometry_fields_default_to_scalar_non_multiplexed():
    iw, cw = built()
    cw._column_picker.value = cw._columns["General Rate Model (GRM)"]

    by_name = {f.name: f for f in cw._column_form.spec.fields}
    assert by_name["axial_dispersion"].kind == "float"
    assert by_name["film_diffusion"].kind == "float"
    assert by_name["pore_diffusion"].kind == "float"


def test_enabling_multiplex_switches_field_to_per_component():
    iw, cw = built()
    cw.components = ["Salt", "Protein"]
    cw._column_picker.value = cw._columns["General Rate Model (GRM)"]

    cw._multiplex_checkboxes["axial_dispersion"].value = True

    by_name = {f.name: f for f in cw._column_form.spec.fields}
    assert by_name["axial_dispersion"].kind == "float_list"
    assert by_name["axial_dispersion"].component_names == ("Salt", "Protein")
    # untouched params stay scalar
    assert by_name["film_diffusion"].kind == "float"


def test_multiplex_checkbox_visibility_matches_column_capabilities():
    iw, cw = built()
    # LumpedRateModelWithoutPores: no particles
    cw._column_picker.value = cw._columns["Lumped Rate Model Without Pores (LRM)"]
    assert cw._multiplex_checkboxes["axial_dispersion"].layout.display == ""
    assert cw._multiplex_checkboxes["film_diffusion"].layout.display == "none"
    assert cw._multiplex_checkboxes["pore_diffusion"].layout.display == "none"


def test_show_optional_parameters_adds_and_removes_column_fields():
    iw, cw = built()
    cw._column_picker.value = cw._columns["General Rate Model (GRM)"]
    required_names = {f.name for f in cw._column_form.spec.fields}
    assert "c" not in required_names  # optional fields hidden by default

    cw._show_optional_column_checkbox.value = True
    shown_names = {f.name for f in cw._column_form.spec.fields}
    assert {"c", "cp", "flow_direction", "pore_accessibility"} <= shown_names
    # still builds a real column with the optional fields' own defaults applied
    assert cw._get_column() is not None

    cw._show_optional_column_checkbox.value = False
    assert {f.name for f in cw._column_form.spec.fields} == required_names


def test_show_optional_parameters_skips_none_valued_and_non_scalar_fields():
    iw, cw = built()
    cw._column_picker.value = cw._columns["General Rate Model (GRM)"]
    cw._binding_picker.value = cw._binding_registry["None"]  # q stays unset without a real isotherm
    cw._show_optional_column_checkbox.value = True

    names = {f.name for f in cw._column_form.spec.fields}
    assert "q" not in names  # None-valued (no bound states configured)
    assert "surface_diffusion" not in names  # None-valued
    assert "discretization" not in names  # nested solver-settings dict, not a scalar field


def test_show_optional_parameters_does_not_apply_to_binding_form():
    iw, cw = built()
    cw._binding_picker.value = cw._binding_registry["Steric Mass Action (SMA)"]
    cw._show_optional_column_checkbox.value = True

    names = {f.name for f in cw._binding_form.spec.fields}
    assert "reference_liquid_phase_conc" not in names


def test_show_optional_binding_parameters_adds_sma_reference_concentrations():
    iw, cw = built()
    cw._binding_picker.value = cw._binding_registry["Steric Mass Action (SMA)"]
    required_names = {f.name for f in cw._binding_form.spec.fields}

    cw._show_optional_binding_checkbox.value = True
    shown_names = {f.name for f in cw._binding_form.spec.fields}
    assert {"reference_liquid_phase_conc", "reference_solid_phase_conc"} <= shown_names
    assert cw._get_column() is not None  # still builds with the optional fields applied

    cw._show_optional_binding_checkbox.value = False
    assert {f.name for f in cw._binding_form.spec.fields} == required_names


def test_show_optional_binding_parameters_does_not_apply_to_column_form():
    iw, cw = built()
    cw._column_picker.value = cw._columns["General Rate Model (GRM)"]
    cw._show_optional_binding_checkbox.value = True

    names = {f.name for f in cw._column_form.spec.fields}
    assert "c" not in names


def test_scalar_column_field_broadcasts_via_cadetprocess():
    iw, cw = built()
    cw.components = ["Salt", "Protein", "Impurity"]
    cw._column_picker.value = cw._columns["General Rate Model (GRM)"]

    column = cw._get_column()
    assert column.axial_dispersion == [column.axial_dispersion[0]] * 3


def test_multiplexed_column_field_keeps_distinct_per_component_values():
    iw, cw = built()
    cw.components = ["Salt", "Protein"]
    cw._column_picker.value = cw._columns["General Rate Model (GRM)"]
    cw._multiplex_checkboxes["axial_dispersion"].value = True

    cw._column_form._elements["axial_dispersion"].value = [1e-8, 2e-8]

    column = cw._get_column()
    assert column.axial_dispersion == [1e-8, 2e-8]


def test_concentration_fields_are_sized_and_named_from_component_system():
    iw, cw = built()
    cw.components = ["Salt", "Protein", "Impurity"]
    cw._model_picker.value = cw._registry["Load–Wash–Elute (LWE)"]

    by_name = {f.name: f for f in cw._model_form.spec.fields}
    assert by_name["c_buffer_a"].component_names == ("Salt", "Protein", "Impurity")
    assert len(by_name["c_buffer_a"].default) == 3
    assert by_name["c_sample"].component_names == ("Salt", "Protein", "Impurity")


def test_export_script_reflects_a_renamed_single_component():
    iw, cw = built()
    cw.components = ["MyProtein"]  # still one component, just renamed

    script = cw.export_script()
    assert "component_system = ComponentSystem(['MyProtein'])" in script

    ns = {}
    exec(compile(script, "<generated>", "exec"), ns)  # noqa: S102
    assert list(ns["component_system"].names) == ["MyProtein"]


def test_breakthrough_sample_buffer_choice_field_targets_the_selected_buffer():
    iw, cw = built()
    cw._model_picker.value = cw._registry["Breakthrough"]

    sample_buffer = cw._model_form.element("sample_buffer")
    assert sample_buffer.option_labels == [
        "Feed inlet (F)", "Buffer A", "Buffer B", "Buffer C", "Buffer D",
    ]
    assert sample_buffer.value == "F"
    assert cw.process.flow_sheet.feed_inlet.flow_rate[0] > 0

    sample_buffer.value = "A"
    assert cw.process.flow_sheet.buffer_a.flow_rate[0] > 0


def test_event_sliders_cover_only_scalar_timing_fields_not_concentration_lists():
    _, cw = built()  # defaults to Pulse Injection
    assert set(cw._event_sliders) == {"cycle_time", "flow_rate"}


def test_event_sliders_change_when_process_template_changes():
    _, cw = built()
    cw._model_picker.value = cw._registry["Load–Wash–Elute (LWE)"]
    assert set(cw._event_sliders) == {
        "delta_t_wash", "delta_t_elute", "delta_t_final_wash", "flow_rate_wash",
    }


def test_moving_event_slider_updates_the_linked_form_field():
    _, cw = built()
    slider = cw._event_sliders["cycle_time"]

    slider.value = slider.value * 2

    assert cw._model_form.element("cycle_time").value == slider.value


def test_editing_form_field_updates_the_linked_event_slider():
    _, cw = built()
    element = cw._model_form.element("flow_rate")

    element.value = element.value * 3

    assert cw._event_sliders["flow_rate"].value == element.value


def test_moving_event_slider_rebuilds_a_preview_process():
    _, cw = built()

    seen = []
    original_build = cw._model_form.spec.build
    cw._model_form.spec.build = lambda values: seen.append(values) or original_build(values)

    cw._event_sliders["cycle_time"].value += 1.0

    assert len(seen) == 1
    assert seen[0]["cycle_time"] == cw._event_sliders["cycle_time"].value


def test_moving_event_slider_with_invalid_column_field_does_not_crash():
    _, cw = built()
    cw._column_form._elements["length"].value = -1.0  # CADET-Process rejects this on setattr

    cw._event_sliders["cycle_time"].value += 1.0  # must not raise despite the column error


def test_event_chart_populates_series_from_parameter_timelines():
    _, cw = built()
    cw._model_picker.value = cw._registry["Step"]  # a clean, valve-event-free timeline set

    series = cw._event_chart.series
    assert len(series) == len(cw.process.parameter_timelines)
    names = {s["name"] for s in series}
    assert names == {"Buffer b"}
    for s in series:
        assert len(s["times"]) == len(s["values"]) == 300
        assert s["times"][0] == 0.0
        assert s["times"][-1] == cw.process.cycle_time / 60.0  # minutes, not seconds


def test_event_chart_updates_when_a_field_changes():
    _, cw = built()
    cw._model_picker.value = cw._registry["Step"]
    first_series = cw._event_chart.series

    cw._model_form.element("cycle_time").value = 7000.0

    assert cw._event_chart.series != first_series
    assert cw._event_chart.series[0]["times"][-1] == 7000.0 / 60.0


def test_event_chart_populates_even_without_an_instrument_bound():
    # Standalone (item #32): ConfigurationWidget already builds a real
    # process (Pulse Feed) with its own real timelines, no Instrument needed.
    cw = ConfigurationWidget()
    assert cw._event_chart.series != []


def test_event_chart_y_label_is_flow_rate_quantity_and_unit():
    _, cw = built()
    cw._model_picker.value = cw._registry["Step"]  # every timeline is *.flow_rate
    assert cw._event_chart.y_label == r"Flow rate / \frac{\mathrm{m}^{3}}{\mathrm{s}}"


def test_cycle_time_slider_is_capped_at_300_minutes_by_default():
    _, cw = built()  # default cycle_time (6000s = 100min) is under the cap
    assert cw._event_sliders["cycle_time"].max == 300.0 * 60.0


def test_cycle_time_slider_cap_stretches_to_fit_an_existing_larger_value():
    _, cw = built()
    cw._model_form.element("cycle_time").value = 400.0 * 60.0  # 400 min is above the 300 min cap

    cw._rebuild_event_sliders()  # normally triggered by a rebuild, called directly here

    assert cw._event_sliders["cycle_time"].max >= 400.0 * 60.0
    assert cw._event_sliders["cycle_time"].value <= cw._event_sliders["cycle_time"].max


def test_switching_column_type_rebuilds_event_sliders_without_stale_links():
    iw, cw = built()
    old_slider = cw._event_sliders["flow_rate"]

    cw._column_picker.selected_index = 1  # switch column from GRM (default) to LRMP

    new_slider = cw._event_sliders["flow_rate"]
    assert new_slider is not old_slider
    old_slider.value = old_slider.value + 1.0  # stale slider is disconnected from the current form
    assert cw._model_form.element("flow_rate").value != old_slider.value


def test_cycle_time_settings_gear_visible_only_when_cycle_time_exists():
    _, cw = built()  # defaults to Pulse Injection, which has cycle_time
    assert cw._process_settings.button.layout.display == ""

    cw._model_picker.value = cw._registry["Load–Wash–Elute (LWE)"]  # no cycle_time field
    assert cw._process_settings.button.layout.display == "none"
    assert cw._process_settings.box.layout.display == "none"


def test_cycle_time_minutes_toggle_swaps_visible_field_and_converts_value():
    _, cw = built()
    seconds_element = cw._model_form.element("cycle_time")
    assert seconds_element.value == 6000.0
    assert seconds_element.layout.display == ""
    assert cw._cycle_time_minutes_element.layout.display == "none"

    cw._cycle_time_unit_checkbox.value = True

    assert seconds_element.layout.display == "none"
    assert cw._cycle_time_minutes_element.layout.display == ""
    assert cw._cycle_time_minutes_element.value == 100.0  # 6000s == 100min


def test_editing_cycle_time_in_minutes_updates_the_real_seconds_field():
    _, cw = built()
    cw._cycle_time_unit_checkbox.value = True

    cw._cycle_time_minutes_element.value = 150.0

    seconds_element = cw._model_form.element("cycle_time")
    assert seconds_element.value == 9000.0  # 150min == 9000s
    assert cw.process.cycle_time == 9000.0  # auto-committed like any other field


def test_cycle_time_unit_checkbox_state_persists_across_a_rebuild():
    iw, cw = built()
    cw._cycle_time_unit_checkbox.value = True

    cw.components = ["Salt", "Protein"]  # triggers _rebuild_forms -> fresh elements

    seconds_element = cw._model_form.element("cycle_time")
    assert seconds_element.layout.display == "none"
    assert cw._cycle_time_minutes_element.layout.display == ""


def test_invalid_field_value_is_not_committed_and_shows_an_inline_error():
    _, cw = built()
    element = cw._model_form.element("flow_rate")  # has validate=require_positive

    element.value = -1.0

    assert not element.is_valid
    assert element.error  # shown inline under the field itself
    assert not cw._model_form.is_valid
    assert cw._model_form.built is None


def test_invalid_field_value_leaves_the_last_good_process_in_place():
    _, cw = built()
    good_process = cw.process
    assert good_process is not None

    cw._model_form.element("flow_rate").value = -1.0  # invalid: blocked before committing

    assert cw.process is good_process  # untouched -- Run/Export still work off it


def test_cadetprocess_level_rejection_surfaces_as_a_status_error_without_crashing():
    _, cw = built()

    cw._column_form._elements["length"].value = -1.0  # no client-side validator for this field

    assert "lower bound" in cw._column_form.status.value.lower()
    assert cw._get_column().length != -1.0  # CADET-Process's own setter rejected it


def test_fixing_an_invalid_value_recommits_automatically():
    _, cw = built()
    element = cw._model_form.element("flow_rate")
    element.value = -1.0
    assert cw._model_form.built is None

    element.value = 3e-6

    assert cw._model_form.is_valid
    assert cw._model_form.built is not None
    assert cw.process is cw._model_form.built


def test_bypassing_column_builds_a_process_with_no_column_at_all():
    # Checked by default (unit is in the flow path); unchecking removes it.
    iw, cw = built()
    iw._unit_checkboxes["column"].value = False
    iw._unit_checkboxes["tubing_pre_column"].value = False
    iw._unit_checkboxes["tubing_post_column"].value = False
    iw._unit_checkboxes["tubing_detectors"].value = False

    assert "column" not in [u.name for u in iw.flow_sheet.units]
    assert cw._column_form is None
    assert cw._binding_form is None
    assert cw.process is not None  # the process template itself needs no column


def test_unit_checkboxes_default_to_only_column_checked():
    iw = InstrumentWidget()
    assert iw._unit_checkboxes["column"].value is True
    assert all(
        cb.value is False for name, cb in iw._unit_checkboxes.items() if name != "column"
    )
    assert set(iw.bypass_units()) == set(iw._unit_checkboxes) - {"column"}


def test_bound_configuration_offers_the_five_lc_templates_and_no_cstr_by_default():
    iw = InstrumentWidget()
    cw = ConfigurationWidget(instrument=iw)

    assert cw._model_picker.option_labels == [
        "Breakthrough",
        "Step",
        "Pulse Injection",
        "Load–Wash–Elute (LWE)",
        "Step Elution",
    ]
    assert "Continuous Stirred Tank Reactor (CSTR)" not in cw._column_picker.option_labels
    assert type(cw.process).__name__ == "Breakthrough"


def test_unbound_configuration_still_offers_pulse_feed_and_cstr():
    cw = ConfigurationWidget()

    assert "Pulse Feed (Single Component)" in cw._model_picker.option_labels
    assert "Continuous Stirred Tank Reactor (CSTR)" in cw._column_picker.option_labels

    cw._column_picker.value = cw._columns["Continuous Stirred Tank Reactor (CSTR)"]
    assert type(cw._get_column()).__name__ == "Cstr"
    assert type(cw.process).__name__ == "Process"


def test_invalid_system_input_clears_the_process_until_it_is_fixed():
    iw, cw = built()
    iw._sample_loop_checkbox.value = True
    seen = []
    cw.add_listener(seen.append)
    assert cw.process is not None

    iw._loop_volume_field.value = 0.0

    assert cw.process is None
    assert seen[-1] is None
    assert "invalid" in cw.status.value

    iw._loop_volume_field.value = 5e-8

    assert cw.process is not None
    assert seen[-1] is cw.process


def test_model_form_edit_does_not_resurrect_a_process_while_the_system_is_invalid():
    iw, cw = built()
    iw._sample_loop_checkbox.value = True
    iw._loop_volume_field.value = 0.0

    cw._model_form.element("flow_rate").value = 2e-6

    assert cw.process is None


def test_bound_configuration_starts_on_breakthrough_with_no_sample_loop():
    iw = InstrumentWidget()
    cw = ConfigurationWidget(instrument=iw)

    assert cw._model_picker.option_labels[cw._model_picker.selected_index] == "Breakthrough"
    assert type(cw.process).__name__ == "Breakthrough"
    assert iw._sample_loop_checkbox.value is False
    assert iw._sample_loop_checkbox.disabled is False
    assert set(iw.bypass_units()) == set(iw._unit_checkboxes) - {"column"}
    assert "sample_loop" not in [u.name for u in iw.flow_sheet.units]


@pytest.mark.parametrize(
    ("label", "process_type"),
    [
        ("Pulse Injection", "PulseInjection"),
        ("Load–Wash–Elute (LWE)", "LWE"),
        ("Step Elution", "StepElution"),
    ],
)
def test_templates_that_need_a_sample_loop_switch_it_on_and_lock_it(label, process_type):
    iw, cw = built()
    cw.components = ["Salt", "Protein"]
    instrument_builds = []
    process_builds = []
    iw.add_listener(instrument_builds.append)
    cw.add_listener(process_builds.append)

    cw._model_picker.value = cw._registry[label]

    assert iw._sample_loop_checkbox.value is True
    assert iw._sample_loop_checkbox.disabled is True
    assert label in iw._loop_lock_note.value
    assert iw._loop_lock_note.layout.display == ""
    assert "sample_loop" in [u.name for u in iw.flow_sheet.units]
    assert type(cw.process).__name__ == process_type
    assert len(instrument_builds) == 1
    assert len(process_builds) == 1


@pytest.mark.parametrize("label", ["Step", "Breakthrough"])
def test_optional_loop_templates_unlock_it_and_restore_the_users_choice(label):
    iw, cw = built()
    cw._model_picker.value = cw._registry["Pulse Injection"]

    cw._model_picker.value = cw._registry[label]

    assert iw._sample_loop_checkbox.value is False
    assert iw._sample_loop_checkbox.disabled is False
    assert iw._loop_lock_note.layout.display == "none"
    assert type(cw.process).__name__ == label

    iw._sample_loop_checkbox.value = True
    cw._model_picker.value = cw._registry["Step Elution"]
    cw._model_picker.value = cw._registry[label]

    assert iw._sample_loop_checkbox.value is True
    assert iw._sample_loop_checkbox.disabled is False


def test_locked_sample_loop_survives_a_state_round_trip():
    iw, cw = built()
    cw._model_picker.value = cw._registry["Pulse Injection"]
    state = cw._snapshot_state()
    assert state.instrument.include_sample_loop is True

    iw2, cw2 = built()
    cw2._apply_state("Imported", state)

    assert type(cw2.process).__name__ == "PulseInjection"
    assert iw2._sample_loop_checkbox.value is True
    assert iw2._sample_loop_checkbox.disabled is True


def test_instrument_state_round_trips_through_snapshot_and_apply_state():
    iw, cw = built()
    iw._unit_checkboxes["mixer"].value = True

    state = cw._snapshot_state()
    iw2, cw2 = built()
    cw2._apply_state("Imported", state)

    assert "mixer" not in iw2.bypass_units()


def test_config_hash_is_set_after_construction_and_changes_with_field_edits():
    _, cw = built()
    assert cw.config_hash is not None

    first_hash = cw.config_hash
    cw._model_form.element("flow_rate").value = 4.4e-6
    assert cw.config_hash != first_hash


def test_snapshot_and_apply_state_round_trips_a_mutated_configuration():
    iw, cw = built()
    cw._column_picker.value = cw._columns["General Rate Model (GRM)"]
    cw._binding_picker.value = cw._binding_registry["Langmuir"]
    cw._column_form.element("length").value = 0.42
    cw._model_form.element("flow_rate").value = 4.4e-6

    state = cw._snapshot_state()

    _, cw2 = built()  # a different widget entirely
    cw2._apply_state("Imported", state)

    assert cw2.config_name == "Imported"
    assert cw2.persistence._name_field.value == "Imported"
    assert cw2.config_hash == cw.config_hash
    assert type(cw2._get_column()).__name__ == "GeneralRateModel"
    assert type(cw2._get_binding_model()).__name__ == "Langmuir"
    assert cw2._column_form.collect_values() == cw._column_form.collect_values()
    assert cw2._model_form.collect_values() == cw._model_form.collect_values()


def test_apply_state_rejects_an_unregistered_template_key():
    _, cw = built()
    state = cw._snapshot_state()
    bad_state = configuration_store.ConfigurationState(
        **{**state.__dict__, "template_key": "Some Removed Template"}
    )
    with pytest.raises(ValueError, match="isn't registered"):
        cw._apply_state("x", bad_state)


def test_apply_state_rejects_an_unregistered_column_key():
    _, cw = built()
    state = cw._snapshot_state()
    bad_state = configuration_store.ConfigurationState(
        **{**state.__dict__, "column_key": "Some Removed Column"}
    )
    with pytest.raises(ValueError, match="isn't registered"):
        cw._apply_state("x", bad_state)


def test_save_button_writes_to_the_store_and_shows_the_path(tmp_path):
    _, cw = built()
    cw.persistence._name_field.value = "Saved Config"

    cw.persistence._on_save(None)

    assert str(tmp_path) in cw.persistence.save_status.value
    name, state = configuration_store.load_from_store(cw.config_hash)
    assert name == "Saved Config"
    assert state == cw._snapshot_state()


def test_import_from_store_restores_a_previously_saved_configuration():
    _, cw = built()
    cw.persistence._name_field.value = "Saved Config"
    cw._model_form.element("flow_rate").value = 7.7e-6
    cw.persistence._on_save(None)
    saved_hash = cw.config_hash

    _, cw2 = built()
    cw2.import_from_store(saved_hash)

    assert cw2.config_name == "Saved Config"
    assert cw2.config_hash == saved_hash
    assert "Imported" in cw2.persistence.save_status.value


def test_import_from_store_with_unknown_hash_shows_an_error():
    _, cw = built()
    cw.import_from_store("deadbeef")
    assert "deadbeef" in cw.persistence.save_status.value


def test_import_hash_button_delegates_to_import_from_store():
    _, cw = built()
    cw.persistence._name_field.value = "Saved Config"
    cw.persistence._on_save(None)
    saved_hash = cw.config_hash

    _, cw2 = built()
    cw2.persistence._import_hash_field.value = saved_hash
    cw2.persistence._on_import_hash_click(None)

    assert cw2.config_hash == saved_hash


def test_file_upload_imports_an_exported_configuration():
    _, cw = built()
    cw.persistence._name_field.value = "Uploaded Config"
    cw._model_form.element("flow_rate").value = 2.2e-6

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "exported.h5"
        state = cw._snapshot_state()
        configuration_store.save_h5(state, "Uploaded Config", path, process=cw.process)
        content = memoryview(path.read_bytes())

    _, cw2 = built()
    cw2.persistence._file_upload.value = (
        {
            "name": "exported.h5",
            "type": "application/x-hdf5",
            "size": len(content),
            "last_modified": dt.datetime.now(),
            "content": content,
        },
    )

    assert cw2.config_name == "Uploaded Config"
    assert cw2.config_hash == cw.config_hash
    assert cw2.persistence._file_upload.value == ()  # cleared so the same file can be re-uploaded


def test_store_dir_defaults_to_none_and_uses_the_default_store(tmp_path):
    _, cw = built()
    cw.persistence._name_field.value = "Default Store Config"
    assert cw.persistence.store_dir is None

    cw.persistence._on_save(None)
    # default store dir is monkeypatched to tmp_path by the isolated_store fixture
    expected_dir = configuration_store.config_dir("Default Store Config", store_dir=tmp_path)
    assert (expected_dir / f"config_{cw.config_hash}.h5").exists()


def test_setting_a_custom_store_dir_is_used_for_save_and_import(tmp_path):
    custom = tmp_path / "my_configs" / "nested"
    _, cw = built()
    cw.persistence._name_field.value = "Custom Folder Config"
    cw.persistence._store_dir_field.value = str(custom)

    cw.persistence._on_set_store_dir(None)

    assert cw.persistence.store_dir == custom
    assert custom.is_dir()  # created on set, even before anything is saved

    cw.persistence._on_save(None)
    expected_dir = configuration_store.config_dir("Custom Folder Config", store_dir=custom)
    assert (expected_dir / f"config_{cw.config_hash}.h5").exists()

    _, cw2 = built()
    cw2.persistence._store_dir_field.value = str(custom)
    cw2.persistence._on_set_store_dir(None)
    cw2.import_from_store(cw.config_hash)
    assert cw2.config_name == "Custom Folder Config"


def test_blank_store_dir_field_resets_to_the_default(tmp_path):
    _, cw = built()
    cw.persistence._store_dir_field.value = str(tmp_path / "custom")
    cw.persistence._on_set_store_dir(None)
    assert cw.persistence.store_dir is not None

    cw.persistence._store_dir_field.value = ""
    cw.persistence._on_set_store_dir(None)
    assert cw.persistence.store_dir is None


def test_invalid_store_dir_shows_an_error_and_does_not_change_store_dir(tmp_path):
    blocked = tmp_path / "not_a_directory"
    blocked.write_text("x")

    _, cw = built()
    cw.persistence._store_dir_field.value = str(blocked / "sub")
    cw.persistence._on_set_store_dir(None)

    assert cw.persistence.store_dir is None
    assert "cadetgui-msg-error" in cw.persistence.save_status.value


def test_save_without_a_name_is_refused(tmp_path):
    _, cw = built()
    cw.persistence._name_field.value = ""  # cleared the default name
    cw.persistence._on_save(None)

    assert "name" in cw.persistence.save_status.value.lower()
    assert list(tmp_path.glob("*.h5")) == []  # nothing written to the store


def test_save_load_details_are_collapsed_by_default_and_toggle():
    _, cw = built()
    assert cw.persistence._save_load_details_box.layout.display == "none"
    assert cw.persistence._btn_toggle_save_load_details.description == "Show details"

    cw.persistence._on_toggle_save_load_details(None)
    assert cw.persistence._save_load_details_box.layout.display == ""
    assert cw.persistence._btn_toggle_save_load_details.description == "Hide details"

    cw.persistence._on_toggle_save_load_details(None)
    assert cw.persistence._save_load_details_box.layout.display == "none"
    assert cw.persistence._btn_toggle_save_load_details.description == "Show details"


def test_workspace_header_is_the_first_section_in_the_panel():
    _, cw = built()
    children = cw.root.children
    # index 0 is the injected style tag, index 1 the panel title
    assert children[2] is cw.workspace_header.root
    assert cw.persistence._name_field in cw.workspace_header.root.children[0].children


def test_name_error_reflects_whether_the_configuration_is_named():
    _, cw = built()
    assert cw.name_error() is None  # has the default name

    cw.persistence._name_field.value = ""
    error = cw.name_error("running a simulation")
    assert error == "Give the configuration a name before running a simulation."


def test_persist_to_store_raises_without_a_name():
    _, cw = built()
    cw.persistence._name_field.value = ""
    try:
        cw.persist_to_store()
        assert False, "should have raised"
    except RuntimeError as exc:
        assert "name" in str(exc).lower()


def test_persist_to_store_saves_and_returns_the_path(tmp_path):
    _, cw = built()
    cw.persistence._name_field.value = "Persisted Config"

    path = cw.persist_to_store()

    expected_dir = configuration_store.config_dir("Persisted Config", store_dir=tmp_path)
    assert path == expected_dir / f"config_{cw.config_hash}.h5"
    assert path.exists()


def test_config_hash_is_computed_fresh_not_cached_stale():
    _, cw = built()
    first = cw.config_hash
    cw._model_form.element("flow_rate").value = 8.8e-6
    assert cw.config_hash != first  # no stale cached value survives a field edit
