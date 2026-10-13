"""Shared fixtures: isolated stores, small models, synchronous threads, a browser."""
from __future__ import annotations

import threading

import cadetgui.io.configuration_store as configuration_store
import cadetgui.io.run_store as run_store
import pytest


@pytest.fixture(autouse=True)
def isolated_stores(tmp_path, monkeypatch):
    """Keep saved configurations and runs in a tmp dir, never in the user's ~/.cadetgui."""
    configs, runs = tmp_path / "configurations", tmp_path / "runs"
    configs.mkdir()
    runs.mkdir()
    monkeypatch.setattr(configuration_store, "default_store_dir", lambda: configs)
    monkeypatch.setattr(run_store, "default_run_store_dir", lambda: runs)
    return configs


@pytest.fixture
def synchronous_threads(monkeypatch):
    """Run background threads inline, so a widget's run finishes before the call returns."""
    monkeypatch.setattr(threading.Thread, "start", lambda self: self.run())


@pytest.fixture
def pulse_process():
    """A small Inlet -> LRM -> Outlet process with a 60 s pulse, fast to simulate."""
    from CADETProcess.processModel import (
        ComponentSystem,
        FlowSheet,
        Inlet,
        LumpedRateModelWithoutPores,
        Outlet,
        Process,
    )

    component_system = ComponentSystem(["A"])
    inlet = Inlet(component_system, "inlet")
    inlet.flow_rate = 1e-7
    column = LumpedRateModelWithoutPores(component_system, "column")
    column.length = 0.1
    column.diameter = 0.01
    column.total_porosity = 0.7
    column.axial_dispersion = 1e-7
    column.c = [0.0]
    column.q = []
    outlet = Outlet(component_system, "outlet")
    flow_sheet = FlowSheet(component_system, "flow_sheet")
    for unit in (inlet, column, outlet):
        flow_sheet.add_unit(unit)
    flow_sheet.add_connection(inlet, column)
    flow_sheet.add_connection(column, outlet)
    process = Process(flow_sheet, "pulse")
    process.cycle_time = 600.0
    process.add_event("load", "flow_sheet.inlet.c", [1.0], 0.0)
    process.add_event("wash", "flow_sheet.inlet.c", [0.0], 60.0)
    return process


@pytest.fixture
def instrument_and_configuration():
    """A default InstrumentWidget and a ConfigurationWidget bound to it."""
    from cadetgui.widgets.instrument import ConfigurationWidget, InstrumentWidget

    instrument = InstrumentWidget()
    return instrument, ConfigurationWidget(instrument=instrument)


@pytest.fixture(scope="session")
def cadet_process_descriptor_metadata():
    """Fail with a precise message when the imported CADET-Process predates PR #435.

    Column/binding/solver descriptors only carry `unit=`/`description=` from that PR on;
    a checkout without it (e.g. an older `dev`) makes the live-metadata tests fail with
    unrelated-looking assertion errors.
    """
    import CADETProcess
    from cadetgui.parameters import get_parameter

    meta = get_parameter("column", "GeneralRateModel", "length")
    if not meta.get("unit") or not meta.get("description"):
        pytest.fail(
            "The imported CADET-Process has no descriptor unit/description metadata "
            "(fau-advanced-separations/CADET-Process PR #435: commit 'Expose "
            "unit/description metadata on column, binding, and solver parameters'). "
            f"Imported from {CADETProcess.__file__}; check that checkout's branch/HEAD "
            "contains that commit.",
            pytrace=False,
        )


@pytest.fixture(scope="session")
def chromium():
    """Headless Chromium for JS view tests; skips when Playwright or its browser is absent."""
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # browser binary not installed
            pytest.skip(f"chromium unavailable: {exc}")
        yield browser
        browser.close()
