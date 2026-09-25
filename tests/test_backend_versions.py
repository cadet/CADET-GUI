from __future__ import annotations

import cadetgui.backend_versions as bv
import cadetgui.simulation as simulation
import cadetgui.widgets.composite.backend_versions as widget_module
import pytest
from cadetgui.widgets.composite import BackendVersionsWidget
from cadetgui.widgets.composite.backend_versions import backend_versions_text


@pytest.fixture(autouse=True)
def _fresh_cache():
    bv.cadet_process_version.cache_clear()
    bv.cadet_core_version.cache_clear()
    yield
    bv.cadet_process_version.cache_clear()
    bv.cadet_core_version.cache_clear()


class _FakeCadet:
    calls = 0

    @property
    def version(self):
        type(self).calls += 1
        return "9.8.7"


class _BrokenCadet:
    def __init__(self):
        raise RuntimeError("no cadet-cli")


def test_cadet_process_version_is_a_string():
    version = bv.cadet_process_version()
    assert isinstance(version, str) and version


def test_cadet_core_version_from_simulator_and_cached(monkeypatch):
    _FakeCadet.calls = 0
    monkeypatch.setattr(simulation, "Cadet", _FakeCadet)
    assert bv.cadet_core_version() == "9.8.7"
    assert bv.cadet_core_version() == "9.8.7"
    assert _FakeCadet.calls == 1


def test_cadet_core_version_none_when_simulator_fails(monkeypatch):
    monkeypatch.setattr(simulation, "Cadet", _BrokenCadet)
    assert bv.cadet_core_version() is None


def test_cadet_core_version_none_when_simulator_missing(monkeypatch):
    monkeypatch.setattr(simulation, "Cadet", None)
    assert bv.cadet_core_version() is None


def test_widget_shows_both_versions(monkeypatch):
    monkeypatch.setattr(simulation, "Cadet", _FakeCadet)
    monkeypatch.setattr(widget_module, "cadet_process_version", lambda: "1.2.3")
    widget = BackendVersionsWidget()
    assert "CADET-Process 1.2.3" in widget._label.value
    assert "CADET-Core 9.8.7" in widget._label.value


def test_widget_shows_not_found_without_crashing(monkeypatch):
    monkeypatch.setattr(simulation, "Cadet", _BrokenCadet)
    widget = BackendVersionsWidget()
    assert "CADET-Core not found" in widget._label.value
    assert "CADET-Core not found" in backend_versions_text()
