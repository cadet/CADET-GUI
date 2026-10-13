"""SimulationWidget: run, signal options, reference and markers."""
from __future__ import annotations

import numpy as np
from cadetgui import SimulationWidget
from CADETProcess.reference import ReferenceIO


def _reference():
    time = np.linspace(0, 600, 61)
    return ReferenceIO("measured", time, (time > 120).astype(float))


def test_simulation_widget_runs_and_offers_signals_by_unit(pulse_process):
    widget = SimulationWidget(pulse_process)
    assert widget.get_value() is None
    seen = []
    widget.add_listener(seen.append)

    results = widget.run()

    assert results is widget.get_value() is seen[0]
    assert widget.view.picker.option_labels == [
        "inlet", "column.inlet", "column.outlet", "outlet"
    ]
    assert widget.view.selected == ("outlet", "inlet")
    assert [s["name"] for s in widget.chart.series] == ["A"]
    assert "simulation_results.solution.outlet.inlet.plot()" in widget.code()
    widget.view.picker.value = ("column", "outlet")
    assert "simulation_results.solution.column.outlet.plot()" in widget.code()

    widget.view.clear()
    assert widget.chart.series == [] and widget.view.selected is None


def test_simulation_widget_reports_a_failed_run(pulse_process):
    pulse_process.flow_sheet.column.length = None
    widget = SimulationWidget(pulse_process)
    assert widget.run() is None
    assert "Simulation failed" in widget.status.value


def test_simulation_widget_overlays_a_reference(pulse_process):
    widget = SimulationWidget(pulse_process, reference=_reference())
    assert [s["name"] for s in widget.chart.series] == ["measured"]
    widget.run()
    assert [s["name"] for s in widget.chart.series] == ["A", "measured"]
    widget.reference = None
    assert [s["name"] for s in widget.chart.series] == ["A"]


def test_simulation_widget_marks_times_in_the_chart_and_code(pulse_process):
    widget = SimulationWidget(pulse_process, markers={"t_R": 126.0})
    assert widget.chart.markers == [{"name": "t_R", "time": 2.1}]
    assert 'ax.axvline(2.1, color="gray", linestyle="--", label="t_R")' in widget.code()
