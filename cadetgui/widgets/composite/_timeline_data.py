from __future__ import annotations

from typing import Any, Optional, Sequence

from ...cadetprocessadapter import (
    CONCENTRATION_UNITS,
    process_phase_spans,
    sample_injection_times,
)

_N_SAMPLES = 300
_M3S_TO_ML_MIN = 6.0e7
_ML_MIN_UNITS = r"\frac{\mathrm{mL}}{\mathrm{min}}"


def _y_label(quantities: set[str]) -> str:
    if len(quantities) != 1:
        return "state"
    (quantity,) = quantities
    if quantity == "c":
        return f"Concentration / {CONCENTRATION_UNITS}"
    label = quantity.replace("_", " ").capitalize()
    return f"{label} / {_ML_MIN_UNITS}" if quantity == "flow_rate" else label


def timeline_chart_data(
    process: Any, component_names: Sequence[str], phase_names: Sequence[str]
) -> Optional[dict[str, Any]]:
    """Sample a process's parameter timelines for the event chart (times in minutes).

    Returns `series`, `y_label`, `phases` and `markers`, or `None` for a non-positive
    cycle time. Valve-state timelines are skipped; flow-only charts are shown in mL/min.
    """
    cycle_time = float(process.cycle_time)
    if cycle_time <= 0:
        return None
    times_s = [cycle_time * i / (_N_SAMPLES - 1) for i in range(_N_SAMPLES)]
    times_min = [t / 60.0 for t in times_s]

    timelines = {
        name: timeline
        for name, timeline in process.parameter_timelines.items()
        if "output_states" not in name.split(".")
    }
    quantities = {name.split(".")[-1] for name in timelines}
    flow_only = quantities == {"flow_rate"}
    scale = _M3S_TO_ML_MIN if flow_only else 1.0

    series = []
    for name, timeline in timelines.items():
        raw = timeline.value(times_s)
        raw = raw.tolist() if hasattr(raw, "tolist") else list(raw)
        n_cols = len(raw[0]) if raw and isinstance(raw[0], (list, tuple)) else 1
        parts = name.split(".")
        unit_op = parts[-2] if len(parts) >= 2 else name
        display_name = unit_op.replace("_", " ").capitalize()
        for col in range(n_cols):
            if n_cols == 1:
                label = display_name
            elif col < len(component_names):
                label = f"{display_name} ({component_names[col]})"
            else:
                label = f"{display_name} [{col}]"
            values = [
                scale * (float(row[col]) if isinstance(row, (list, tuple)) else float(row))
                for row in raw
            ]
            series.append({"name": label, "times": times_min, "values": values})
    if flow_only:
        series = [s for s in series if any(s["values"])] or series

    return {
        "series": series,
        "y_label": _y_label(quantities),
        "phases": [
            {"name": p["name"], "start": p["start"] / 60.0, "end": p["end"] / 60.0}
            for p in process_phase_spans(process, phase_names)
        ],
        "markers": [
            {"name": "Sample injection", "time": t / 60.0}
            for t in sample_injection_times(process)
        ],
    }
