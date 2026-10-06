import subprocess
import sys

import cadetgui
import cadetgui.widgets


def test_benches_import_from_the_top_level():
    from cadetgui import CharacterizationWorkbenchWidget, WorkbenchWidget
    from cadetgui.widgets import composite

    assert WorkbenchWidget is composite.WorkbenchWidget
    assert CharacterizationWorkbenchWidget is composite.CharacterizationWorkbenchWidget


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
