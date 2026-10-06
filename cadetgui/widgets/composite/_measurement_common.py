"""Labels, summaries and small helpers shared by the measurement panes."""

from __future__ import annotations

import copy
import dataclasses
import html
import math
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Tuple

import ipywidgets as W

from ...cadetprocessadapter import (
    BYPASSABLE_UNITS,
    INSTRUMENT_TEMPLATES,
    STANDALONE_TEMPLATES,
    UNIT_LABELS,
    FieldSpec,
    parse_float_list,
    signal_label,
    template_required_units,
)
from ...characterization.comparison import Comparison
from ...characterization.guide import (
    CHAIN_BY_ID,
    EXPERIMENT_TYPES,
    SALT_ROLE,
)
from ...characterization.study import Study
from ...io.configuration_store import ConfigurationState
from .._help import term_html
from .._status import status_html

if TYPE_CHECKING:
    pass


ML_PER_MIN = 1e-6 / 60.0

# Column-mapping dropdown options: (label, ColumnRole value).
COLUMN_ROLE_OPTIONS = [
    ("Time [s]", "time_s"),
    ("Time [min]", "time_min"),
    ("Volume [mL]", "volume_ml"),
    ("Signal channel", "signal"),
    ("Skip", "skip"),
]

# Substring of a `Comparison.problems()` message -> what the user should do about it.
_ADVICE: Tuple[Tuple[str, str], ...] = (
    ("No flat baseline found", "Set a baseline window under Advanced → Baseline and "
     "scaling over a stretch without signal from the probe, e.g. after the peak."),
    ("No data loaded", "Add the measurement again from its data file, or pick a loaded run "
     "under Advanced → Data and alignment → Data run."),
    ("Unknown channel", "Pick one of the run's channels under Advanced → Data and alignment "
     "→ Channel."),
    ("No run-log marker", "Pick the injection marker under Advanced → Data and alignment, "
     "or choose 'None / manual' and enter where the injection happened."),
    ("flow rate", "Enter the run's flow rate (mL/min) under Advanced → Data and alignment, "
     "or set one in the process."),
    ("target_area", "Enter the target area (the injected amount) under Advanced → "
     "Baseline and scaling, or switch normalization off."),
    ("Unknown normalization", "Pick a normalization under Advanced → Baseline and scaling."),
    ("Unknown metric", "Pick a metric under Advanced → Comparison."),
    ("not in the recipe", "Tick only components of the recipe under Advanced → Simulated "
     "signal → Components."),
    ("Recipe cannot be built", "Open the process in Process Configuration, fix it there and "
     "apply it to this measurement."),
    ("Solution path", "Pick an observation point that is in the flow path under Advanced → "
     "Simulated signal."),
    ("is declared as", "Pick a component with a fitting role under Advanced → Simulated "
     "signal → Component, or change the component's role under System → Components."),
    ("is not a declared component", "Declare it under System → Components, or pick a "
     "declared component under Advanced → Simulated signal → Component."),
    ("No component picked", "Pick the component under Advanced → Simulated signal → "
     "Component."),
)


def _format(value: Optional[float]) -> str:
    return "" if value is None else f"{value:g}"


def _format_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(_format_value(v) for v in value)
    return f"{value:g}" if isinstance(value, float) else str(value)


def _optional_float(text: str) -> Optional[float]:
    text = text.strip()
    return float(text) if text else None


def _check_float(text: str) -> Optional[str]:
    try:
        _optional_float(text)
    except ValueError:
        return "Enter a number or leave blank."
    return None


def _check_float_list(text: str) -> Optional[str]:
    try:
        parse_float_list(text)
    except ValueError:
        return "Enter numbers separated by commas, or leave blank."
    return None


def _template_fields(recipe: ConfigurationState) -> List[FieldSpec]:
    """Return the recipe's process-template fields (the values `overrides` may replace)."""
    registry = INSTRUMENT_TEMPLATES if recipe.instrument is not None else STANDALONE_TEMPLATES
    factory = registry.get(recipe.template_key)
    if factory is None:
        return []
    # The template factories only read `component_system.names` before `build` is called.
    stub = SimpleNamespace(component_system=SimpleNamespace(names=list(recipe.components)))
    return [f for f in factory(stub).fields if f.kind in ("float", "float_list", "choice")]


def _template_registry(recipe: ConfigurationState) -> Dict[str, Callable[..., Any]]:
    return INSTRUMENT_TEMPLATES if recipe.instrument is not None else STANDALONE_TEMPLATES


def recipe_with_template(recipe: ConfigurationState, template_key: str) -> ConfigurationState:
    """Return `recipe` running process template `template_key` with its default method values.

    The flow rate is kept; the sample loop is put in the flow path if the template needs it.
    """
    factory = _template_registry(recipe)[template_key]
    changed = dataclasses.replace(recipe, template_key=template_key)
    values = {f.name: copy.deepcopy(f.default) for f in _template_fields(changed)}
    flow_rate = _recipe_flow_rate(recipe)
    if flow_rate is not None:
        for key in ("flow_rate", "flow_rate_wash"):
            if key in values:
                values[key] = flow_rate
    instrument = recipe.instrument
    if instrument is not None and "sample_loop" in template_required_units(factory):
        instrument = dataclasses.replace(instrument, include_sample_loop=True)
    return dataclasses.replace(changed, model_values=values, instrument=instrument)


def _template_options(recipe: ConfigurationState) -> List[Tuple[str, str]]:
    options = [(key, key) for key in _template_registry(recipe)]
    if recipe.template_key not in dict(options).values():
        options.append((f"{recipe.template_key} (not available)", recipe.template_key))
    return options


def _step_of(comparison: Comparison) -> Optional[str]:
    """Return the id of the chain step `comparison`'s experiment type feeds, if any."""
    experiment_type = EXPERIMENT_TYPES.get(comparison.experiment_type or "")
    if experiment_type is None or experiment_type.step_id not in CHAIN_BY_ID:
        return None
    return experiment_type.step_id


def _recipe_flow_rate(recipe: ConfigurationState) -> Optional[float]:
    value = recipe.model_values.get("flow_rate", recipe.model_values.get("flow_rate_wash"))
    return float(value) if value is not None else None


def _observed_unit(solution_path: str) -> str:
    return solution_path.partition(".")[0]


def observation_label(solution_path: str) -> str:
    """Return a readable name of the observation point `solution_path`."""
    unit, _, port = solution_path.partition(".")
    return signal_label(unit, port.split(".")[0]) if port else solution_path


def detector_label(channel: str) -> str:
    """Return a detector name for a measured channel: "UV", "Conductivity", or the channel."""
    lowered = (channel or "").lower()
    if "uv" in lowered:
        return "UV"
    if "cond" in lowered:
        return "Conductivity"
    return channel or "no channel"


def channel_label(channel: str) -> str:
    """Return the detector name followed by the raw channel name, e.g. "UV (UV 1_280)"."""
    detector = detector_label(channel)
    return detector if detector == channel else f"{detector} ({channel})"


def measurement_caption(comparison: Comparison) -> str:
    """Return a plain-language one-liner: experiment type, channel, where it is read, probe."""
    experiment = EXPERIMENT_TYPES.get(comparison.experiment_type or "")
    parts = [experiment.label if experiment is not None else "No experiment type"]
    location = observation_label(comparison.solution_path)
    parts.append(f"{channel_label(comparison.channel)}, read at {location}")
    if comparison.probe:
        parts.append(f"probe: {comparison.probe}")
    return " · ".join(parts)


def _flow_path_units(recipe: ConfigurationState) -> Tuple[List[str], List[str]]:
    """Return the in-line and the bypassed units of `recipe`, in flow order."""
    instrument = recipe.instrument
    if instrument is None:
        return ["column"], []
    bypass = set(instrument.bypass_units)
    in_line = []
    for unit in BYPASSABLE_UNITS:
        if unit == "tubing_pre_column" and instrument.include_sample_loop:
            in_line.append("sample_loop")
        if unit not in bypass:
            in_line.append(unit)
    return in_line, [u for u in BYPASSABLE_UNITS if u in bypass]


def recipe_summary_html(comparison: Comparison) -> str:
    """Return a plain-language table of `comparison`'s recipe and observation point."""
    recipe = comparison.recipe
    experiment_type = EXPERIMENT_TYPES.get(comparison.experiment_type or "")
    flow_rate = comparison.resolved_flow_rate or _recipe_flow_rate(recipe)
    if flow_rate is None:
        flow_text = "not set"
    else:
        source = "this run" if comparison.flow_rate is not None else "from the recipe"
        flow_text = f"{flow_rate / ML_PER_MIN:.4g} mL/min ({source})"
    in_line, bypassed = _flow_path_units(recipe)
    labels = [UNIT_LABELS.get(u, u) for u in in_line]
    rows: List[Tuple[str, str]] = [
        ("Experiment type", html.escape(experiment_type.label if experiment_type else "not set")),
        ("Data", html.escape(
            f"{comparison.data_file or 'no file'} · {channel_label(comparison.channel)}"
        )),
        ("Process template", html.escape(recipe.template_key)),
        ("Flow rate", html.escape(flow_text)),
        ("Components", html.escape(", ".join(recipe.components))),
        (term_html("probe", "Probe"), html.escape(comparison.probe or "not set")),
        ("Column model", html.escape(f"{recipe.column_key}; binding: {recipe.binding_key}")),
        ("Column", "in line" if "column" in in_line else "bypassed (replaced by a union)"),
        (term_html("flow path", "Flow path"), html.escape(" → ".join(labels))),
        ("Bypassed", html.escape(", ".join(UNIT_LABELS.get(u, u) for u in bypassed) or "none")),
    ]
    if recipe.instrument is not None:
        loop = recipe.instrument
        rows.append((
            "Sample loop",
            f"{loop.sample_loop_volume * 1e9:.4g} µL" if loop.include_sample_loop else "not used",
        ))
    observed = observation_label(comparison.solution_path)
    if experiment_type is not None:
        observed += f" ({experiment_type.detector})"
    rows.append((term_html("observation point", "Observation point"), html.escape(observed)))
    body = "".join(
        f"<tr><th>{label}</th>"
        f"<td>{value}</td></tr>"
        for label, value in rows
    )
    return f"<table class='cadetgui-recipe-summary'>{body}</table>"


def _column_settings(recipe: ConfigurationState) -> str:
    values = recipe.column_values
    scaled = (
        ("length", "length", 100.0, "cm"),
        ("diameter", "diameter", 1000.0, "mm"),
        ("bed_porosity", "bed porosity", 1.0, ""),
        ("particle_porosity", "particle porosity", 1.0, ""),
    )
    parts = []
    for key, label, factor, unit in scaled:
        value = values.get(key)
        if isinstance(value, (int, float)):
            parts.append(f"{label} {value * factor:.4g}{' ' + unit if unit else ''}")
    return " · ".join(parts)


def system_summary_html(recipe: ConfigurationState) -> str:
    """Return a plain-language table of the system every new measurement starts from.

    Hardware (flow path, bypassed units, sample loop), flow rate, and the column settings
    that seed each measurement; the process template is left out, since each measurement
    gets its own from its experiment type.
    """
    flow_rate = _recipe_flow_rate(recipe)
    in_line, bypassed = _flow_path_units(recipe)
    rows: List[Tuple[str, str]] = [
        (term_html("flow path", "Flow path"),
         html.escape(" → ".join(UNIT_LABELS.get(u, u) for u in in_line))),
        ("Bypassed", html.escape(", ".join(UNIT_LABELS.get(u, u) for u in bypassed) or "none")),
    ]
    if recipe.instrument is not None:
        loop = recipe.instrument
        rows.append((
            "Sample loop",
            f"{loop.sample_loop_volume * 1e9:.4g} µL" if loop.include_sample_loop else "not used",
        ))
    rows += [
        ("Flow rate", "not set" if flow_rate is None
         else html.escape(f"{flow_rate / ML_PER_MIN:.4g} mL/min")),
        ("Column model", html.escape(recipe.column_key)),
        ("Binding model", html.escape(recipe.binding_key)),
    ]
    settings = _column_settings(recipe)
    if settings:
        rows.append((
            "Column settings",
            html.escape(settings) + " <small>(starting values of every new measurement)</small>",
        ))
    body = "".join(f"<tr><th>{label}</th><td>{value}</td></tr>" for label, value in rows)
    return f"<table class='cadetgui-recipe-summary'>{body}</table>"


def problems_html(problems: Sequence[str]) -> str:
    """Return `problems` as error lines, each followed by what to do about it."""
    if not problems:
        return status_html("ok", "No problems found.")
    lines = []
    for problem in problems:
        advice = next((a for key, a in _ADVICE if key in problem), None)
        line = status_html("error", problem)
        if advice:
            line += f"<div class='cadetgui-note'>What to do: {html.escape(advice)}</div>"
        lines.append(line)
    return "".join(f"<div>{line}</div>" for line in lines)


def _detector_hint(channel: str) -> Optional[str]:
    lower = channel.lower()
    if "cond" in lower:
        return "conductivity"
    if "uv" in lower:
        return "UV"
    return None


def component_options(
    study: Study, roles: Optional[Sequence[str]]
) -> List[Tuple[str, str]]:
    """Return the declared components as choices, those whose role is in `roles` first.

    A non-fitting one is marked, e.g. "Acetone (system tracer — not a small tracer)". With
    `roles` None every component but the salt fits.
    """
    fits = [
        c for c in study.components
        if (c.role in roles if roles is not None else c.role != SALT_ROLE)
    ]
    others = [c for c in study.components if c not in fits and c.role != SALT_ROLE]
    wanted = " or ".join(roles or ())
    return [(f"{c.name} ({c.role})", c.name) for c in fits] + [
        (f"{c.name} ({c.role} — not a {wanted})", c.name) for c in others
    ]


def _title(text_html: str) -> W.HTML:
    return W.HTML(f"<div class='cadetgui-section-title'>{text_html}</div>")


def _row(*children: W.Widget) -> W.HBox:
    row = W.HBox(list(children), layout=W.Layout(flex_flow="row wrap"))
    row.add_class("cadetgui-row")
    return row


def _note(text_html: str = "") -> W.HTML:
    note = W.HTML(text_html)
    note.add_class("cadetgui-note")
    return note


def _same(a: Optional[float], b: Optional[float]) -> bool:
    return a is None or (b is not None and math.isclose(a, float(b), rel_tol=1e-9))
