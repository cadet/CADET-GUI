"""Public imports: lazy top-level and io exports, domain packages, backend versions."""

import importlib
import subprocess
import sys

import cadetgui
import cadetgui.backend_versions as bv
import cadetgui.process_model.simulation as simulation
import pytest
from cadetgui.widgets.benches.frame import backend_versions_text


@pytest.mark.parametrize(
    "name, module",
    [
        ("InstrumentWorkbenchWidget", "cadetgui.widgets.benches"),
        ("CharacterizationWorkbenchWidget", "cadetgui.widgets.benches"),
        ("ProcessWidget", "cadetgui.widgets.process_model"),
    ],
)
def test_top_level_names_are_the_package_objects(name, module):
    assert getattr(cadetgui, name) is getattr(importlib.import_module(module), name)


@pytest.mark.parametrize("package", [cadetgui, cadetgui.io], ids=lambda p: p.__name__)
def test_unknown_lazy_attribute_raises(package):
    with pytest.raises(AttributeError):
        package.NotAThing  # noqa: B018


@pytest.mark.parametrize(
    "package",
    [
        "cadetgui.io",
        "cadetgui.parameters",
        "cadetgui.widgets",
        "cadetgui.widgets.ui",
        "cadetgui.widgets.elements",
        "cadetgui.widgets.diagrams",
        "cadetgui.widgets.instrument",
        "cadetgui.widgets.estimation",
        "cadetgui.widgets.characterization",
    ],
)
def test_every_exported_name_resolves(package):
    module = importlib.import_module(package)
    for name in module.__all__:
        assert getattr(module, name) is not None, name


def test_bench_kit_is_exported_from_widgets():
    import cadetgui.widgets

    assert {"SidebarShell", "bench_root", "status_html", "style_tag"} <= set(
        cadetgui.widgets.__all__
    )


@pytest.mark.parametrize(
    "code, expected",
    [
        ("import sys, cadetgui; print('cadetgui.widgets' in sys.modules)", "False"),
        (
            "import sys, cadetgui.io; cadetgui.io.ExperimentalRun; "
            "print('cadetgui.io.configuration_store' in sys.modules)",
            "False",
        ),
    ],
    ids=["top level", "io"],
)
def test_imports_stay_lazy(code, expected):
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.stdout.strip() == expected


class _FakeCadet:
    calls = 0

    @property
    def version(self):
        type(self).calls += 1
        return "9.8.7"


class _BrokenCadet:
    def __init__(self):
        raise RuntimeError("no cadet-cli")


@pytest.mark.parametrize("cadet, expected", [(_FakeCadet, "9.8.7"), (_BrokenCadet, None)])
def test_backend_versions_are_read_once_and_tolerate_a_missing_core(monkeypatch, cadet, expected):
    monkeypatch.setattr(simulation, "Cadet", cadet)
    bv.cadet_core_version.cache_clear()
    _FakeCadet.calls = 0
    try:
        assert bv.cadet_core_version() == bv.cadet_core_version() == expected
        assert _FakeCadet.calls == (cadet is _FakeCadet)
        assert bv.cadet_process_version()
        text = backend_versions_text()
        assert ("CADET-Core not found" in text) == (expected is None)
    finally:
        bv.cadet_core_version.cache_clear()
