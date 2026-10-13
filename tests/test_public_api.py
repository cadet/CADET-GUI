import subprocess
import sys

import cadetgui
import cadetgui.widgets


def test_benches_and_object_widgets_import_from_the_top_level():
    from cadetgui import (
        CharacterizationWorkbenchWidget,
        InstrumentWorkbenchWidget,
        ProcessWidget,
    )
    from cadetgui.widgets import benches, process_model

    assert InstrumentWorkbenchWidget is benches.InstrumentWorkbenchWidget
    assert CharacterizationWorkbenchWidget is benches.CharacterizationWorkbenchWidget
    assert ProcessWidget is process_model.ProcessWidget


def test_domain_packages_export_their_widgets():
    from cadetgui.widgets import characterization, estimation, instrument

    for package in (instrument, estimation, characterization):
        for name in package.__all__:
            assert getattr(package, name) is not None


def test_top_level_import_does_not_load_the_widgets():
    code = "import sys, cadetgui; print('cadetgui.widgets' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.stdout.strip() == "False"


def test_bench_kit_is_exported_from_widgets():
    for name in cadetgui.widgets.__all__:
        assert getattr(cadetgui.widgets, name) is not None
    assert {"SidebarShell", "bench_root", "status_html", "style_tag"} <= set(
        cadetgui.widgets.__all__
    )


def test_unknown_top_level_attribute_raises():
    try:
        cadetgui.NotAThing  # noqa: B018
    except AttributeError:
        return
    raise AssertionError("expected AttributeError")
