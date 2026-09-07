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

    cw._components.value = 2
    new_column = cw._get_column()
    assert new_column is not original_column
    assert new_column.n_comp == 2
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
    assert ns["component_system"].n_comp == cw._components.value

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
