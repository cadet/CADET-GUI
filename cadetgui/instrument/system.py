"""The LC system: its units, column and binding models, and which inlets a process drives."""

from __future__ import annotations

from typing import Any, Dict, Optional

from CADETProcess.instruments import Step
from CADETProcess.processModel import (
    ChromatographicColumnBase,
    Cstr,
    GeneralRateModel,
    Langmuir,
    Linear,
    LumpedRateModelWithoutPores,
    LumpedRateModelWithPores,
    StericMassAction,
)

# Units `LCFlowSheet(bypass_units=...)` accepts (mirrors its unexported `_BYPASSABLE`).
BYPASSABLE_UNITS: tuple[str, ...] = (
    "mixer", "tubing_pre_injection", "tubing_pre_column",
    "column", "tubing_post_column", "tubing_detectors",
)

# Mixer/tubing units with their own parameter form and dead-volume seeding. The column's
# own form belongs to ConfigurationWidget; this set only covers the instrument's hardware.
CONFIGURABLE_UNITS: tuple[str, ...] = (
    "mixer", "tubing_pre_injection", "tubing_pre_column", "tubing_post_column", "tubing_detectors",
)

# Non-degenerate starting values; CADET-Core has no canonical default for these.
_TUBING_SEED_DEFAULTS: Dict[str, float] = {
    "diameter": 0.5e-3, "length": 0.1, "axial_dispersion": 1e-7,
}
UNIT_SEED_DEFAULTS: Dict[str, Dict[str, float]] = {
    "mixer": {"init_liquid_volume": 1e-6},
    "tubing_pre_injection": _TUBING_SEED_DEFAULTS,
    "tubing_pre_column": _TUBING_SEED_DEFAULTS,
    "tubing_post_column": _TUBING_SEED_DEFAULTS,
    "tubing_detectors": _TUBING_SEED_DEFAULTS,
}

# Plain names for every LCFlowSheet unit.
UNIT_LABELS: dict[str, str] = {
    "buffer_a": "Buffer A",
    "buffer_b": "Buffer B",
    "buffer_c": "Buffer C",
    "buffer_d": "Buffer D",
    "feed_inlet": "Feed",
    "mixer": "Mixer",
    "tubing_pre_injection": "Tubing (pre injection)",
    "sample_loop": "Sample loop",
    "tubing_pre_column": "Tubing (pre column)",
    "column": "Column",
    "tubing_post_column": "Tubing (post column)",
    "tubing_detectors": "Tubing (detectors)",
    "outlet": "Outlet",
    "waste": "Waste outlet",
}

INLET_UNITS = ("buffer_a", "buffer_b", "buffer_c", "buffer_d", "feed_inlet")


def active_inlets(process: Any) -> list[str]:
    """Names of the LC inlets a process actually drives (a flow-rate event is set on them)."""
    driven = {
        event.parameter_path.split(".")[1]
        for event in process.events
        if event.parameter_path.startswith("flow_sheet.")
        and event.parameter_path.endswith(".flow_rate")
    }
    driven.update(equilibration_inlets(process))
    return [name for name in INLET_UNITS if name in driven]


def equilibration_inlets(process: Any) -> list[str]:
    """Inlets that only pre-equilibrate the system before the process starts (Step: buffer A)."""
    return ["buffer_a"] if isinstance(process, Step) else []


def inlet_contents(process: Any) -> dict[str, list[str]]:
    """Component names each driven inlet carries; `"sample_loop"` is listed when it holds sample."""
    flow_sheet = process.flow_sheet
    names = list(flow_sheet.component_system.names)
    units = flow_sheet.units_dict
    contents: dict[str, list[str]] = {}
    for name in [*active_inlets(process), "sample_loop"]:
        if name not in units:
            continue
        found = [n for n, c in zip(names, units[name].c) if any(_as_list(c))]
        if found or name != "sample_loop":
            contents[name] = found
    return contents


def _as_list(value: Any) -> list[Any]:
    return list(value) if hasattr(value, "__iter__") else [value]


# `LCFlowSheet(ColumnModel=...)` takes the class itself. CSTR is standalone-only: it is not
# a `ChromatographicColumnBase`, so it does not fit LCFlowSheet's column slot.
COLUMN_MODELS: Dict[str, type] = {
    "General Rate Model (GRM)": GeneralRateModel,
    "Lumped Rate Model With Pores (LRMP)": LumpedRateModelWithPores,
    "Lumped Rate Model Without Pores (LRM)": LumpedRateModelWithoutPores,
    "Continuous Stirred Tank Reactor (CSTR)": Cstr,
}

INSTRUMENT_COMPATIBLE_COLUMNS: frozenset[str] = frozenset(
    key for key, cls in COLUMN_MODELS.items() if issubclass(cls, ChromatographicColumnBase)
)

# "None" first so a ChoiceField defaults to it; LCFlowSheet keeps the column's NoBinding.
BINDING_MODELS: Dict[str, Optional[type]] = {
    "None": None,
    "Linear": Linear,
    "Langmuir": Langmuir,
    "Steric Mass Action (SMA)": StericMassAction,
}
