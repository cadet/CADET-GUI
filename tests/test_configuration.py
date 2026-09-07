from __future__ import annotations

import warnings

from cadetgui.widgets.composite import ConfigurationWidget

warnings.filterwarnings("ignore", category=UserWarning)


def test_configuration_widget_renders_default_forms():
    cw = ConfigurationWidget()
    assert cw._column_picker.option_labels == ["GRM", "LRMP", "LRM", "CSTR"]
    assert len(cw._column_form_box.children) == 1
    assert len(cw._model_form_box.children) == 1


def test_configuration_widget_builds_process_on_both_applies():
    cw = ConfigurationWidget()
    cw._column_form._on_apply(None)
    cw._model_form._on_apply(None)

    assert cw.process is not None
    assert type(cw.process).__name__ == "BatchElution"


def test_configuration_widget_notifies_listeners_on_build():
    cw = ConfigurationWidget()
    seen = []
    cw.add_listener(seen.append)

    cw._column_form._on_apply(None)
    cw._model_form._on_apply(None)

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
    assert original_column.n_comp == 1

    cw._components.value = ["Salt", "Protein"]
    new_column = cw._get_column()
    assert new_column is not original_column
    assert new_column.n_comp == 2
    assert list(new_column.component_system.names) == ["Salt", "Protein"]
    # the stale 1-component column must not linger in the cache
    assert original_column not in cw._column_cache.values()


def test_export_script_raises_before_anything_is_built():
    cw = ConfigurationWidget()
    try:
        cw.export_script()
        assert False, "should have raised"
    except RuntimeError as exc:
        assert "Apply" in str(exc)


def test_export_script_button_shows_error_status_before_build():
    cw = ConfigurationWidget()
    cw._on_export(None)
    assert "Apply" in cw.status.value
    assert cw._script_out.layout.display == "none"


def test_export_script_produces_executable_equivalent_process():
    import numpy as np

    cw = ConfigurationWidget()
    cw._column_form._on_apply(None)
    cw._model_form._on_apply(None)

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
    cw._column_form._on_apply(None)
    cw._model_form._on_apply(None)

    cw._on_export(None)
    assert "process = " in cw._script_out.value
    assert cw._script_out.layout.display == ""
    assert "generated" in cw.status.value.lower()


def test_binding_model_defaults_to_none_matching_cadetprocess_default():
    cw = ConfigurationWidget()
    assert cw._binding_picker.option_labels[0] == "None"
    assert cw._binding_form.spec.fields == []  # NoBinding has no required_parameters


def test_switching_binding_model_rebuilds_its_form():
    cw = ConfigurationWidget()
    cw._binding_picker.value = cw._binding_registry["Langmuir"]
    assert {f.name for f in cw._binding_form.spec.fields} == {
        "adsorption_rate",
        "desorption_rate",
        "capacity",
    }


def test_applying_binding_form_attaches_it_to_the_column():
    cw = ConfigurationWidget()
    cw._binding_picker.value = cw._binding_registry["Linear"]
    cw._binding_form._on_apply(None)

    column = cw._get_column()
    assert type(column.binding_model).__name__ == "Linear"


def test_switching_column_type_keeps_binding_model_attachable():
    """Regression test: binding model and column must share one ComponentSystem
    instance (CADET-Process rejects a mismatch), and each column factory gets
    its own fresh ComponentSystem — so a binding model cached against a
    since-replaced column must not be reused as-is."""
    cw = ConfigurationWidget()
    cw._binding_picker.value = cw._binding_registry["Linear"]
    cw._binding_form._on_apply(None)

    cw._column_picker.value = cw._columns["LRMP"]  # different column, different ComponentSystem
    cw._binding_form._on_apply(None)  # must not raise / must not fail validation

    assert cw._binding_form.built is not None
    assert "Built successfully" in cw._binding_form.status.value
    column = cw._get_column()
    assert type(column.binding_model).__name__ == "Linear"
    assert column.binding_model.component_system is column.component_system


def test_export_script_includes_binding_model_and_round_trips():
    import numpy as np
    from cadetgui.simulation import run_process

    cw = ConfigurationWidget()
    cw._binding_picker.value = cw._binding_registry["Linear"]
    cw._column_form._on_apply(None)
    cw._binding_form._on_apply(None)
    cw._model_form._on_apply(None)

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


def test_components_field_defaults_to_one_named_component():
    cw = ConfigurationWidget()
    assert cw._components.value == ["Component 1"]
    assert cw._get_column().n_comp == 1
    assert list(cw._get_column().component_system.names) == ["Component 1"]


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
    cw._column_form._on_apply(None)
    cw._binding_form._on_apply(None)

    column = cw._get_column()
    assert column.binding_model.n_comp == 2
    assert cw._binding_form.status.value == "<em>Built successfully.</em>"
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


def test_column_geometry_fields_default_to_scalar_non_multiplexed():
    cw = ConfigurationWidget()
    cw._column_picker.value = cw._columns["GRM"]

    by_name = {f.name: f for f in cw._column_form.spec.fields}
    assert by_name["axial_dispersion"].kind == "float"
    assert by_name["film_diffusion"].kind == "float"
    assert by_name["pore_diffusion"].kind == "float"


def test_enabling_multiplex_switches_field_to_per_component():
    cw = ConfigurationWidget()
    cw._components.value = ["Salt", "Protein"]
    cw._column_picker.value = cw._columns["GRM"]

    cw._multiplex_checkboxes["axial_dispersion"].value = True

    by_name = {f.name: f for f in cw._column_form.spec.fields}
    assert by_name["axial_dispersion"].kind == "float_list"
    assert by_name["axial_dispersion"].component_names == ("Salt", "Protein")
    # untouched params stay scalar
    assert by_name["film_diffusion"].kind == "float"


def test_multiplex_settings_hidden_for_column_without_any_applicable_param():
    cw = ConfigurationWidget()
    cw._column_picker.value = cw._columns["CSTR"]
    assert cw._btn_settings.layout.display == "none"


def test_multiplex_checkbox_visibility_matches_column_capabilities():
    cw = ConfigurationWidget()
    cw._column_picker.value = cw._columns["LRM"]  # LumpedRateModelWithoutPores: no particles
    assert cw._multiplex_checkboxes["axial_dispersion"].layout.display == ""
    assert cw._multiplex_checkboxes["film_diffusion"].layout.display == "none"
    assert cw._multiplex_checkboxes["pore_diffusion"].layout.display == "none"


def test_scalar_column_field_broadcasts_via_cadetprocess_on_apply():
    cw = ConfigurationWidget()
    cw._components.value = ["Salt", "Protein", "Impurity"]
    cw._column_picker.value = cw._columns["GRM"]

    cw._column_form._on_apply(None)
    column = cw._get_column()
    assert column.axial_dispersion == [column.axial_dispersion[0]] * 3


def test_multiplexed_column_field_keeps_distinct_per_component_values():
    cw = ConfigurationWidget()
    cw._components.value = ["Salt", "Protein"]
    cw._column_picker.value = cw._columns["GRM"]
    cw._multiplex_checkboxes["axial_dispersion"].value = True

    cw._column_form._elements["axial_dispersion"].value = [1e-8, 2e-8]
    cw._column_form._on_apply(None)

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
    cw._column_form._on_apply(None)
    cw._binding_form._on_apply(None)
    cw._model_form._on_apply(None)

    script = cw.export_script()
    assert "component_system = ComponentSystem(['MyProtein'])" in script

    ns = {}
    exec(compile(script, "<generated>", "exec"), ns)  # noqa: S102
    assert list(ns["component_system"].names) == ["MyProtein"]
