from __future__ import annotations

import warnings

from cadetgui.widgets.composite import ConfigurationWidget

warnings.filterwarnings("ignore", category=UserWarning)


def test_configuration_widget_renders_default_forms():
    cw = ConfigurationWidget()
    assert cw._column_picker.option_labels == [
        "General Rate Model (GRM)",
        "Lumped Rate Model With Pores (LRMP)",
        "Lumped Rate Model Without Pores (LRM)",
        "Continuous Stirred Tank Reactor (CSTR)",
    ]
    assert len(cw._column_form_box.children) == 1
    assert len(cw._model_form_box.children) == 1


def test_configuration_widget_builds_process_automatically_with_defaults():
    cw = ConfigurationWidget()

    assert cw.process is not None
    assert type(cw.process).__name__ == "BatchElution"


def test_configuration_widget_notifies_listeners_on_a_valid_field_change():
    cw = ConfigurationWidget()
    seen = []
    cw.add_listener(seen.append)

    cw._model_form.element("flow_rate").value = 2e-6

    assert len(seen) == 1
    assert seen[0] is cw.process


def test_configuration_widget_rebuilds_forms_on_model_change():
    cw = ConfigurationWidget()
    first_title = cw._model_form.spec.title

    cw._model_picker.selected_index = 1
    assert cw._model_form.spec.title != first_title
    assert len(cw._model_form_box.children) == 1


def test_configuration_widget_rebuilds_column_on_component_change():
    cw = ConfigurationWidget()
    original_column = cw._get_column()
    assert original_column.n_comp == 2  # Batch Elution's auto-added default

    cw._components.value = ["Salt", "Protein", "Impurity"]
    new_column = cw._get_column()
    assert new_column is not original_column
    assert new_column.n_comp == 3
    assert list(new_column.component_system.names) == ["Salt", "Protein", "Impurity"]
    # the stale 2-component column must not linger in the cache
    assert original_column not in cw._column_cache.values()


def test_export_script_raises_when_nothing_has_been_built():
    # With auto-commit, this state isn't reachable through the default
    # registries (their defaults always build successfully) -- force it
    # directly to keep the guard clause itself covered.
    cw = ConfigurationWidget()
    cw.process = None
    cw._column_form = None
    cw._binding_form = None
    cw._model_form = None
    try:
        cw.export_script()
        assert False, "should have raised"
    except RuntimeError as exc:
        assert "column" in str(exc).lower()


def test_export_script_button_shows_error_status_when_nothing_has_been_built():
    cw = ConfigurationWidget()
    cw.process = None
    cw._column_form = None
    cw._binding_form = None
    cw._model_form = None
    cw._on_export(None)
    assert "column" in cw.status.value.lower()
    assert cw._script_out.layout.display == "none"


def test_export_script_produces_executable_equivalent_process():
    import numpy as np

    cw = ConfigurationWidget()

    script = cw.export_script()
    ns = {}
    exec(compile(script, "<generated>", "exec"), ns)  # noqa: S102

    assert type(ns["process"]) is type(cw.process)
    assert type(ns["column"]) is type(cw._get_column())
    assert ns["component_system"].n_comp == len(cw._components.value)
    assert list(ns["component_system"].names) == cw._components.value

    from cadetgui.simulation import run_process

    res_widget = run_process(cw.process)
    res_script = run_process(ns["process"])
    unit = next(iter(res_widget.solution))
    assert np.array_equal(
        res_widget.solution[unit]["outlet"].solution,
        res_script.solution[unit]["outlet"].solution,
    )


def test_export_script_button_populates_textarea_on_success():
    cw = ConfigurationWidget()

    cw._on_export(None)
    assert "process = " in cw._script_out.value
    assert cw._script_out.layout.display == ""
    assert "generated" in cw.status.value.lower()


def test_binding_model_defaults_to_linear():
    cw = ConfigurationWidget()
    assert cw._binding_picker.option_labels[0] == "None"  # still first in the dropdown list
    selected = cw._binding_picker.option_labels[cw._binding_picker.selected_index]
    assert selected == "Linear"
    names = {f.name for f in cw._binding_form.spec.fields}
    assert names == {"adsorption_rate", "desorption_rate", "is_kinetic"}


def test_switching_binding_model_rebuilds_its_form():
    cw = ConfigurationWidget()
    cw._binding_picker.value = cw._binding_registry["Langmuir"]
    assert {f.name for f in cw._binding_form.spec.fields} == {
        "adsorption_rate",
        "desorption_rate",
        "capacity",
        "is_kinetic",
    }


def test_selecting_binding_model_attaches_it_to_the_column():
    cw = ConfigurationWidget()
    cw._binding_picker.value = cw._binding_registry["Linear"]

    column = cw._get_column()
    assert type(column.binding_model).__name__ == "Linear"


def test_switching_column_type_keeps_binding_model_attachable():
    """Regression test: binding model and column must share one ComponentSystem
    instance (CADET-Process rejects a mismatch), and each column factory gets
    its own fresh ComponentSystem — so a binding model cached against a
    since-replaced column must not be reused as-is."""
    cw = ConfigurationWidget()
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

    cw = ConfigurationWidget()
    cw._binding_picker.value = cw._binding_registry["Linear"]

    script = cw.export_script()
    assert "column.binding_model = Linear(" in script

    ns = {}
    exec(compile(script, "<generated>", "exec"), ns)  # noqa: S102
    assert type(ns["column"].binding_model).__name__ == "Linear"

    res_widget = run_process(cw.process)
    res_script = run_process(ns["process"])
    unit = next(iter(res_widget.solution))
    assert np.array_equal(
        res_widget.solution[unit]["outlet"].solution,
        res_script.solution[unit]["outlet"].solution,
    )


def test_components_field_defaults_to_two_named_components():
    # Batch Elution is the default template and needs a feed + eluent
    # component, so construction auto-adds a second one (see
    # _maybe_autoadd_component / _TEMPLATES_REQUIRING_MULTIPLE_COMPONENTS).
    cw = ConfigurationWidget()
    assert cw._components.value == ["Component 1", "Component 2"]
    assert cw._get_column().n_comp == 2
    assert list(cw._get_column().component_system.names) == ["Component 1", "Component 2"]


def test_component_minimum_and_note_match_the_selected_template():
    cw = ConfigurationWidget()  # defaults to Batch Elution
    assert cw._components.min_components == 2
    assert cw._component_note.layout.display == ""
    assert "2 components" in cw._component_note.value

    cw._model_picker.value = cw._registry["Pulse Feed (Single Component)"]
    assert cw._components.min_components == 1
    assert cw._component_note.layout.display == "none"

    cw._model_picker.value = cw._registry["Load–Wash–Elute (LWE)"]
    assert cw._components.min_components == 2
    assert cw._component_note.layout.display == ""


def test_renaming_components_rebuilds_column_with_new_names():
    cw = ConfigurationWidget()
    cw._components.value = ["Salt", "Protein"]

    column = cw._get_column()
    assert column.n_comp == 2
    assert list(column.component_system.names) == ["Salt", "Protein"]


def test_binding_model_scales_to_multiple_named_components():
    cw = ConfigurationWidget()
    cw._components.value = ["Salt", "Protein"]
    cw._binding_picker.value = cw._binding_registry["Linear"]

    column = cw._get_column()
    assert column.binding_model.n_comp == 2
    assert cw._binding_form.status.value == ""
    # NOTE: applying the model form itself (batch_elution_spec/lwe_spec) is not
    # exercised with >1 component here — those specs hard-code single-value
    # concentration defaults (e.g. c_feed=[10.0]) that CADET-Process rejects
    # for n_comp != 1. Pre-existing adapter-layer limitation, unrelated to
    # component naming; column/binding config already scale correctly, as
    # this test shows. See ai-docs/REQUIREMENTS.md.


def test_binding_form_fields_get_component_names_matching_component_system():
    cw = ConfigurationWidget()
    cw._components.value = ["Salt", "Protein"]
    cw._binding_picker.value = cw._binding_registry["Linear"]

    by_name = {f.name: f for f in cw._binding_form.spec.fields}
    assert by_name["adsorption_rate"].component_names == ("Salt", "Protein")
    assert by_name["desorption_rate"].component_names == ("Salt", "Protein")


def test_binding_form_exposes_is_kinetic_defaulting_to_true():
    cw = ConfigurationWidget()
    cw._binding_picker.value = cw._binding_registry["Linear"]

    element = cw._binding_form.element("is_kinetic")
    assert element.value is True  # CADET-Process's own default
    assert cw._get_column().binding_model.is_kinetic is True


def test_unchecking_is_kinetic_commits_to_the_real_binding_model():
    cw = ConfigurationWidget()
    cw._binding_picker.value = cw._binding_registry["Langmuir"]

    cw._binding_form.element("is_kinetic").value = False

    assert cw._get_column().binding_model.is_kinetic is False


def test_no_binding_does_not_get_an_is_kinetic_field():
    cw = ConfigurationWidget()
    cw._binding_picker.value = cw._binding_registry["None"]
    assert "is_kinetic" not in {f.name for f in cw._binding_form.spec.fields}


def test_column_geometry_fields_default_to_scalar_non_multiplexed():
    cw = ConfigurationWidget()
    cw._column_picker.value = cw._columns["General Rate Model (GRM)"]

    by_name = {f.name: f for f in cw._column_form.spec.fields}
    assert by_name["axial_dispersion"].kind == "float"
    assert by_name["film_diffusion"].kind == "float"
    assert by_name["pore_diffusion"].kind == "float"


def test_enabling_multiplex_switches_field_to_per_component():
    cw = ConfigurationWidget()
    cw._components.value = ["Salt", "Protein"]
    cw._column_picker.value = cw._columns["General Rate Model (GRM)"]

    cw._multiplex_checkboxes["axial_dispersion"].value = True

    by_name = {f.name: f for f in cw._column_form.spec.fields}
    assert by_name["axial_dispersion"].kind == "float_list"
    assert by_name["axial_dispersion"].component_names == ("Salt", "Protein")
    # untouched params stay scalar
    assert by_name["film_diffusion"].kind == "float"


def test_multiplex_checkboxes_hidden_for_column_without_any_applicable_param():
    cw = ConfigurationWidget()
    cw._column_picker.value = cw._columns["Continuous Stirred Tank Reactor (CSTR)"]
    # The gear itself stays visible -- "Show optional parameters" always applies.
    assert cw._btn_settings.layout.display != "none"
    assert all(cb.layout.display == "none" for cb in cw._multiplex_checkboxes.values())


def test_show_optional_parameters_adds_and_removes_column_fields():
    cw = ConfigurationWidget()
    cw._column_picker.value = cw._columns["General Rate Model (GRM)"]
    required_names = {f.name for f in cw._column_form.spec.fields}
    assert "c" not in required_names  # optional fields hidden by default

    cw._show_optional_checkbox.value = True
    shown_names = {f.name for f in cw._column_form.spec.fields}
    assert {"c", "cp", "flow_direction", "pore_accessibility"} <= shown_names
    # still builds a real column with the optional fields' own defaults applied
    assert cw._get_column() is not None

    cw._show_optional_checkbox.value = False
    assert {f.name for f in cw._column_form.spec.fields} == required_names


def test_show_optional_parameters_skips_none_valued_and_non_scalar_fields():
    cw = ConfigurationWidget()
    cw._column_picker.value = cw._columns["General Rate Model (GRM)"]
    cw._binding_picker.value = cw._binding_registry["None"]  # q stays unset without a real isotherm
    cw._show_optional_checkbox.value = True

    names = {f.name for f in cw._column_form.spec.fields}
    assert "q" not in names  # None-valued (no bound states configured)
    assert "surface_diffusion" not in names  # None-valued
    assert "discretization" not in names  # nested solver-settings dict, not a scalar field


def test_show_optional_parameters_does_not_apply_to_binding_form():
    cw = ConfigurationWidget()
    cw._binding_picker.value = cw._binding_registry["Steric Mass Action (SMA)"]
    cw._show_optional_checkbox.value = True

    names = {f.name for f in cw._binding_form.spec.fields}
    assert "reference_liquid_phase_conc" not in names


def test_show_optional_binding_parameters_adds_sma_reference_concentrations():
    cw = ConfigurationWidget()
    cw._binding_picker.value = cw._binding_registry["Steric Mass Action (SMA)"]
    required_names = {f.name for f in cw._binding_form.spec.fields}

    cw._show_optional_binding_checkbox.value = True
    shown_names = {f.name for f in cw._binding_form.spec.fields}
    assert {"reference_liquid_phase_conc", "reference_solid_phase_conc"} <= shown_names
    assert cw._get_column() is not None  # still builds with the optional fields applied

    cw._show_optional_binding_checkbox.value = False
    assert {f.name for f in cw._binding_form.spec.fields} == required_names


def test_show_optional_binding_parameters_does_not_apply_to_column_form():
    cw = ConfigurationWidget()
    cw._column_picker.value = cw._columns["General Rate Model (GRM)"]
    cw._show_optional_binding_checkbox.value = True

    names = {f.name for f in cw._column_form.spec.fields}
    assert "c" not in names


def test_multiplex_checkbox_visibility_matches_column_capabilities():
    cw = ConfigurationWidget()
    # LumpedRateModelWithoutPores: no particles
    cw._column_picker.value = cw._columns["Lumped Rate Model Without Pores (LRM)"]
    assert cw._multiplex_checkboxes["axial_dispersion"].layout.display == ""
    assert cw._multiplex_checkboxes["film_diffusion"].layout.display == "none"
    assert cw._multiplex_checkboxes["pore_diffusion"].layout.display == "none"


def test_scalar_column_field_broadcasts_via_cadetprocess():
    cw = ConfigurationWidget()
    cw._components.value = ["Salt", "Protein", "Impurity"]
    cw._column_picker.value = cw._columns["General Rate Model (GRM)"]

    column = cw._get_column()
    assert column.axial_dispersion == [column.axial_dispersion[0]] * 3


def test_multiplexed_column_field_keeps_distinct_per_component_values():
    cw = ConfigurationWidget()
    cw._components.value = ["Salt", "Protein"]
    cw._column_picker.value = cw._columns["General Rate Model (GRM)"]
    cw._multiplex_checkboxes["axial_dispersion"].value = True

    cw._column_form._elements["axial_dispersion"].value = [1e-8, 2e-8]

    column = cw._get_column()
    assert column.axial_dispersion == [1e-8, 2e-8]


def test_concentration_fields_are_sized_and_named_from_component_system():
    cw = ConfigurationWidget()
    cw._components.value = ["Salt", "Protein", "Impurity"]
    cw._model_picker.value = cw._registry["Batch Elution"]

    by_name = {f.name: f for f in cw._model_form.spec.fields}
    assert by_name["c_feed"].component_names == ("Salt", "Protein", "Impurity")
    assert len(by_name["c_feed"].default) == 3
    assert by_name["c_eluent"].component_names == ("Salt", "Protein", "Impurity")


def test_export_script_reflects_a_renamed_single_component():
    cw = ConfigurationWidget()
    cw._components.value = ["MyProtein"]  # still one component, just renamed

    script = cw.export_script()
    assert "component_system = ComponentSystem(['MyProtein'])" in script

    ns = {}
    exec(compile(script, "<generated>", "exec"), ns)  # noqa: S102
    assert list(ns["component_system"].names) == ["MyProtein"]


def test_event_sliders_cover_only_scalar_timing_fields_not_concentration_lists():
    cw = ConfigurationWidget()  # defaults to Batch Elution
    assert set(cw._event_sliders) == {"flow_rate", "feed_duration", "cycle_time"}


def test_event_sliders_change_when_process_template_changes():
    cw = ConfigurationWidget()
    cw._model_picker.value = cw._registry["Load–Wash–Elute (LWE)"]
    assert set(cw._event_sliders) == {
        "flow_rate", "load_duration", "wash_duration",
        "gradient_duration", "final_wash_duration",
    }


def test_moving_event_slider_updates_the_linked_form_field():
    cw = ConfigurationWidget()
    slider = cw._event_sliders["feed_duration"]

    slider.value = slider.value * 2

    assert cw._model_form.element("feed_duration").value == slider.value


def test_editing_form_field_updates_the_linked_event_slider():
    cw = ConfigurationWidget()
    element = cw._model_form.element("flow_rate")

    element.value = element.value * 3

    assert cw._event_sliders["flow_rate"].value == element.value


def test_moving_event_slider_rebuilds_a_preview_process():
    cw = ConfigurationWidget()

    seen = []
    original_build = cw._model_form.spec.build
    cw._model_form.spec.build = lambda values: seen.append(values) or original_build(values)

    cw._event_sliders["cycle_time"].value += 1.0

    assert len(seen) == 1
    assert seen[0]["cycle_time"] == cw._event_sliders["cycle_time"].value


def test_moving_event_slider_with_invalid_column_field_does_not_crash():
    cw = ConfigurationWidget()
    cw._column_form._elements["length"].value = -1.0  # CADET-Process rejects this on setattr

    cw._event_sliders["cycle_time"].value += 1.0  # must not raise despite the column error


def test_event_chart_populates_series_from_parameter_timelines_on_construction():
    cw = ConfigurationWidget()  # defaults to Batch Elution, valid out of the box

    series = cw._event_chart.series
    assert len(series) == len(cw.process.parameter_timelines)
    # display names are the unit-operation name, not the raw dotted
    # CADET-Process path (e.g. "Eluent", not "flow_sheet.eluent.flow_rate")
    names = {s["name"] for s in series}
    assert names == {"Eluent", "Feed"}
    for s in series:
        assert len(s["times"]) == len(s["values"]) == 300
        assert s["times"][0] == 0.0
        assert s["times"][-1] == cw.process.cycle_time / 60.0  # minutes, not seconds


def test_event_chart_updates_when_a_field_changes():
    cw = ConfigurationWidget()
    first_series = cw._event_chart.series

    cw._model_form.element("cycle_time").value = 7000.0

    assert cw._event_chart.series != first_series
    assert cw._event_chart.series[0]["times"][-1] == 7000.0 / 60.0


def test_event_chart_clears_when_nothing_is_selectable():
    cw = ConfigurationWidget()
    assert cw._event_chart.series  # non-empty to start

    cw._column_picker.value = None

    assert cw._event_chart.series == []


def test_event_chart_y_label_is_flow_rate_quantity_and_unit():
    cw = ConfigurationWidget()  # Batch Elution: every timeline is *.flow_rate
    assert cw._event_chart.y_label == "Flow rate / m^3/s"


def test_cycle_time_slider_is_capped_at_300_minutes_by_default():
    cw = ConfigurationWidget()  # default cycle_time (6000s = 100min) is under the cap
    assert cw._event_sliders["cycle_time"].max == 300.0 * 60.0


def test_cycle_time_slider_cap_stretches_to_fit_an_existing_larger_value():
    cw = ConfigurationWidget()
    cw._model_form.element("cycle_time").value = 400.0 * 60.0  # 400 min is above the 300 min cap

    cw._rebuild_event_sliders()  # normally triggered by a rebuild, called directly here

    assert cw._event_sliders["cycle_time"].max >= 400.0 * 60.0
    assert cw._event_sliders["cycle_time"].value <= cw._event_sliders["cycle_time"].max


def test_switching_column_type_rebuilds_event_sliders_without_stale_links():
    cw = ConfigurationWidget()
    old_slider = cw._event_sliders["flow_rate"]

    cw._column_picker.selected_index = 1  # switch column from GRM (default) to LRMP

    new_slider = cw._event_sliders["flow_rate"]
    assert new_slider is not old_slider
    old_slider.value = old_slider.value + 1.0  # stale slider is disconnected from the current form
    assert cw._model_form.element("flow_rate").value != old_slider.value


def test_cycle_time_settings_gear_visible_only_when_cycle_time_exists():
    cw = ConfigurationWidget()  # defaults to Batch Elution, which has cycle_time
    assert cw._btn_process_settings.layout.display == ""

    cw._model_picker.value = cw._registry["Load–Wash–Elute (LWE)"]  # no cycle_time field
    assert cw._btn_process_settings.layout.display == "none"
    assert cw._process_settings_box.layout.display == "none"


def test_cycle_time_minutes_toggle_swaps_visible_field_and_converts_value():
    cw = ConfigurationWidget()
    seconds_element = cw._model_form.element("cycle_time")
    assert seconds_element.value == 6000.0
    assert seconds_element.layout.display == ""
    assert cw._cycle_time_minutes_element.layout.display == "none"

    cw._cycle_time_unit_checkbox.value = True

    assert seconds_element.layout.display == "none"
    assert cw._cycle_time_minutes_element.layout.display == ""
    assert cw._cycle_time_minutes_element.value == 100.0  # 6000s == 100min


def test_editing_cycle_time_in_minutes_updates_the_real_seconds_field():
    cw = ConfigurationWidget()
    cw._cycle_time_unit_checkbox.value = True

    cw._cycle_time_minutes_element.value = 150.0

    seconds_element = cw._model_form.element("cycle_time")
    assert seconds_element.value == 9000.0  # 150min == 9000s
    assert cw.process.cycle_time == 9000.0  # auto-committed like any other field


def test_cycle_time_unit_checkbox_state_persists_across_a_rebuild():
    cw = ConfigurationWidget()
    cw._cycle_time_unit_checkbox.value = True

    cw._components.value = ["Salt", "Protein"]  # triggers _rebuild_forms -> fresh elements

    seconds_element = cw._model_form.element("cycle_time")
    assert seconds_element.layout.display == "none"
    assert cw._cycle_time_minutes_element.layout.display == ""


def test_invalid_field_value_is_not_committed_and_shows_an_inline_error():
    cw = ConfigurationWidget()
    element = cw._model_form.element("flow_rate")  # has validate=require_positive

    element.value = -1.0

    assert not element.is_valid
    assert element.error  # shown inline under the field itself
    assert not cw._model_form.is_valid
    assert cw._model_form.built is None


def test_invalid_field_value_leaves_the_last_good_process_in_place():
    cw = ConfigurationWidget()
    good_process = cw.process
    assert good_process is not None

    cw._model_form.element("flow_rate").value = -1.0  # invalid: blocked before committing

    assert cw.process is good_process  # untouched -- Run/Export still work off it


def test_cadetprocess_level_rejection_surfaces_as_a_status_error_without_crashing():
    cw = ConfigurationWidget()

    cw._column_form._elements["length"].value = -1.0  # no client-side validator for this field

    assert "lower bound" in cw._column_form.status.value.lower()
    assert cw._get_column().length != -1.0  # CADET-Process's own setter rejected it


def test_fixing_an_invalid_value_recommits_automatically():
    cw = ConfigurationWidget()
    element = cw._model_form.element("flow_rate")
    element.value = -1.0
    assert cw._model_form.built is None

    element.value = 3e-6

    assert cw._model_form.is_valid
    assert cw._model_form.built is not None
    assert cw.process is cw._model_form.built


def test_pulse_feed_builds_a_process_for_a_cstr():
    cw = ConfigurationWidget()
    cw._column_picker.value = cw._columns["Continuous Stirred Tank Reactor (CSTR)"]
    cw._model_picker.value = cw._registry["Pulse Feed (Single Component)"]
    # Pulse Feed doesn't need the second component Batch Elution auto-added.
    cw._components.value = ["Component 1"]

    assert type(cw.process).__name__ == "Process"
    assert cw.process.cycle_time == 6000.0
    timeline = cw.process.parameter_timelines["flow_sheet.feed.c"]
    assert timeline.value([0.0]).flatten().tolist() == [10.0]
    assert timeline.value([70.0]).flatten().tolist() == [0.0]  # past the 60s pulse_duration


def test_pulse_feed_component_picker_targets_only_the_selected_component():
    cw = ConfigurationWidget()
    cw._column_picker.value = cw._columns["Continuous Stirred Tank Reactor (CSTR)"]
    cw._components.value = ["Salt", "Protein"]
    cw._model_picker.value = cw._registry["Pulse Feed (Single Component)"]

    component = cw._model_form.element("component")
    assert component.option_labels == ["Salt", "Protein"]
    timeline = cw.process.parameter_timelines["flow_sheet.feed.c"]
    assert timeline.value([0.0]).flatten().tolist() == [10.0, 0.0]

    component.value = "Protein"

    timeline = cw.process.parameter_timelines["flow_sheet.feed.c"]
    assert timeline.value([0.0]).flatten().tolist() == [0.0, 10.0]


def test_pulse_feed_event_chart_shows_feed_concentration():
    cw = ConfigurationWidget()
    cw._column_picker.value = cw._columns["Continuous Stirred Tank Reactor (CSTR)"]
    cw._model_picker.value = cw._registry["Pulse Feed (Single Component)"]
    # Pulse Feed doesn't need the second component Batch Elution auto-added.
    cw._components.value = ["Component 1"]

    assert [s["name"] for s in cw._event_chart.series] == ["Feed"]
    assert cw._event_chart.y_label == "Concentration / mol/m^3_IV"


def test_pulse_feed_gets_sliders_for_its_scalar_fields_but_not_the_component_picker():
    cw = ConfigurationWidget()
    cw._column_picker.value = cw._columns["Continuous Stirred Tank Reactor (CSTR)"]
    cw._model_picker.value = cw._registry["Pulse Feed (Single Component)"]

    assert set(cw._event_sliders) == {"concentration", "flow_rate", "pulse_duration", "cycle_time"}


def test_pulse_feed_export_script_round_trips():
    cw = ConfigurationWidget()
    cw._column_picker.value = cw._columns["Continuous Stirred Tank Reactor (CSTR)"]
    cw._model_picker.value = cw._registry["Pulse Feed (Single Component)"]

    script = cw.export_script()
    ns: dict = {}
    exec(compile(script, "<generated>", "exec"), ns)  # noqa: S102

    assert ns["process"].cycle_time == cw.process.cycle_time
    exported_timeline = ns["process"].parameter_timelines["flow_sheet.feed.c"]
    original_timeline = cw.process.parameter_timelines["flow_sheet.feed.c"]
    assert exported_timeline.value([0.0]).tolist() == original_timeline.value([0.0]).tolist()
