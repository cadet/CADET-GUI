from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from CADETProcess.instruments import LCFlowSheet
from CADETProcess.processModel import ComponentSystem, Process

from .cadetprocessadapter import (
    BINDING_MODELS,
    COLUMN_MODELS,
    CONFIGURABLE_UNITS,
    INSTRUMENT_TEMPLATES,
    STANDALONE_TEMPLATES,
    UNIT_SEED_DEFAULTS,
    FieldSpec,
    ModelSpec,
    build_parameter_config_spec,
    measurable_signal_options,
)
from .configuration_store import ConfigurationState
from .parameter_store import has_parameter

__all__ = [
    "build_process",
    "RecipeCheck",
    "check_recipe",
    "clear_recipe_checks",
    "recipe_key",
]


def _field_default(f: FieldSpec) -> Any:
    """Coerce a field's spec default to the type its rendered element would hold.

    Mirrors `FormRenderer`'s `_coerced_default` for a field absent from the saved values.
    """
    if f.kind == "float":
        return float(f.default) if f.default is not None else 0.0
    if f.kind == "float_list":
        return list(f.default) if f.default else [0.0]
    if f.kind == "bool":
        return bool(f.default)
    if f.kind == "choice":
        return f.default
    return str(f.default) if f.default is not None else ""


def _coerce_value(kind: str, raw: Any) -> Any:
    """Coerce a raw stored value to the type its element's value trait would hold."""
    if kind == "float":
        return float(raw)
    if kind == "float_list":
        return [float(v) for v in raw]
    if kind == "bool":
        return bool(raw)
    if kind == "text":
        return str(raw) if raw is not None else ""
    return raw


def _apply_spec(spec: ModelSpec, values: Mapping[str, Any]) -> Any:
    """Build `spec` from `values`, falling back to each field's default.

    Mirrors `FormRenderer.set_values()` followed by its auto-commit: every field is
    set, from `values` if present else its default, then `spec.build` is called once.
    """
    if spec.build is None:
        raise RuntimeError(f"{spec.title!r} has no 'build' function.")
    final: Dict[str, Any] = {}
    for f in spec.fields:
        raw = values[f.name] if f.name in values else _field_default(f)
        coerced = _coerce_value(f.kind, raw)
        final[f.name] = f.transform(coerced) if f.transform else coerced
    return spec.build(final)


def _seed_unit_values(
    flow_sheet: LCFlowSheet, bypass: List[str], unit_values: Mapping[str, Mapping[str, float]]
) -> None:
    """Seed mixer/tubing dead-volume parameters, mirroring `InstrumentWidget`'s seeding.

    A bypassed unit is skipped: `LCFlowSheet` never removes the mixer but forces its own
    near-zero bypass volume, which a seeded value would silently undo.
    """
    for name in CONFIGURABLE_UNITS:
        if name in bypass or name not in flow_sheet:
            continue
        unit = flow_sheet[name]
        for pname, value in (unit_values.get(name) or UNIT_SEED_DEFAULTS[name]).items():
            setattr(unit, pname, value)


def _apply_column_and_binding(
    column: Any, state: ConfigurationState, binding_model: Optional[Any]
) -> None:
    column_spec = build_parameter_config_spec(
        column, multiplex=state.multiplex_state, include_optional=state.show_optional_column
    )
    _apply_spec(column_spec, state.column_values)

    if binding_model is None:
        return
    binding_spec = build_parameter_config_spec(
        binding_model, include_optional=state.show_optional_binding
    )
    column.binding_model = _apply_spec(binding_spec, state.binding_values)


def _build_instrument_process(
    state: ConfigurationState, overrides: Optional[Mapping[str, Any]]
) -> Process:
    instrument = state.instrument
    assert instrument is not None

    column_cls = COLUMN_MODELS.get(state.column_key)
    if column_cls is None:
        raise ValueError(f"Unknown column model {state.column_key!r}.")
    if state.binding_key not in BINDING_MODELS:
        raise ValueError(f"Unknown binding model {state.binding_key!r}.")
    binding_cls = BINDING_MODELS[state.binding_key]
    template_factory = INSTRUMENT_TEMPLATES.get(state.template_key)
    if template_factory is None:
        raise ValueError(f"Unknown process template {state.template_key!r}.")

    component_system = ComponentSystem(list(state.components))
    bypass = list(instrument.bypass_units)
    include_loop = bool(instrument.include_sample_loop)
    flow_sheet = LCFlowSheet(
        component_system,
        sample_loop_volume=float(instrument.sample_loop_volume) if include_loop else None,
        sample_loop_diameter=(
            float(instrument.sample_loop_diameter)
            if include_loop and not instrument.sample_loop_diameter_auto
            else None
        ),
        ColumnModel=None if "column" in bypass else column_cls,
        BindingModel=binding_cls,
        bypass_units=bypass or None,
    )

    _seed_unit_values(flow_sheet, bypass, instrument.unit_values)

    if "column" not in bypass:
        column = flow_sheet.column
        _apply_column_and_binding(column, state, getattr(column, "binding_model", None))

    model_spec = template_factory(flow_sheet)
    model_values = {**state.model_values, **(overrides or {})}
    return _apply_spec(model_spec, model_values)


def _build_standalone_process(
    state: ConfigurationState, overrides: Optional[Mapping[str, Any]]
) -> Process:
    column_cls = COLUMN_MODELS.get(state.column_key)
    if column_cls is None:
        raise ValueError(f"Unknown column model {state.column_key!r}.")
    if state.binding_key not in BINDING_MODELS:
        raise ValueError(f"Unknown binding model {state.binding_key!r}.")
    binding_cls = BINDING_MODELS[state.binding_key]
    template_factory = STANDALONE_TEMPLATES.get(state.template_key)
    if template_factory is None:
        raise ValueError(f"Unknown process template {state.template_key!r}.")

    component_system = ComponentSystem(list(state.components))
    column = column_cls(component_system, name="column")

    binding_model = (
        binding_cls(column.component_system, name="binding_model")
        if binding_cls is not None
        else None
    )
    _apply_column_and_binding(column, state, binding_model)

    model_spec = template_factory(column)
    model_values = {**state.model_values, **(overrides or {})}
    return _apply_spec(model_spec, model_values)


def build_process(
    state: ConfigurationState, *, overrides: Optional[Mapping[str, Any]] = None
) -> Process:
    """Rebuild the `Process` a saved `ConfigurationState` describes, without any widget.

    Headless equivalent of constructing `InstrumentWidget` + `ConfigurationWidget` (or a
    bare `ConfigurationWidget` when `state.instrument` is `None`) and calling their
    `_apply_state`: the same registries (`INSTRUMENT_TEMPLATES`/`STANDALONE_TEMPLATES`,
    `COLUMN_MODELS`, `BINDING_MODELS`), the same `LCFlowSheet` construction (sample loop,
    bypass units, mixer/tubing dead-volume seeding) and the same column/binding/model
    parameter application order.

    `overrides` replaces entries in `state.model_values` (e.g. flow rate, phase
    durations) for the process template only; column, binding and instrument values are
    always taken from `state`, so a comparison can vary the run's timing/flow off a
    saved recipe without saving a new configuration.
    """
    if state.instrument is not None:
        return _build_instrument_process(state, overrides)
    return _build_standalone_process(state, overrides)


@dataclass(frozen=True)
class RecipeCheck:
    """Read-only facts about the process a recipe builds, or why it cannot be built.

    `error` is set (and everything else empty) when `build_process` raised.
    """

    error: Optional[str]
    units: Tuple[str, ...] = ()
    species: Tuple[str, ...] = ()
    signal_options: Tuple[Tuple[str, Tuple[str, str]], ...] = ()
    _process: Optional[Process] = field(default=None, repr=False, compare=False)

    def has_parameter(self, path: str) -> bool:
        """Return whether the built process carries the parameter at `path`."""
        return self._process is not None and has_parameter(self._process, path)


_CHECK_CACHE_SIZE = 64
_check_cache: "OrderedDict[str, RecipeCheck]" = OrderedDict()


def recipe_key(state: ConfigurationState, overrides: Optional[Mapping[str, Any]] = None) -> str:
    """Return a string that is equal for equal `(state, overrides)` contents."""
    return json.dumps([asdict(state), dict(overrides or {})], sort_keys=True, default=str)


def check_recipe(
    state: ConfigurationState, overrides: Optional[Mapping[str, Any]] = None
) -> RecipeCheck:
    """Return `RecipeCheck` for `build_process(state, overrides=overrides)`, memoized by content.

    The built process stays private to the check, so it is never mutated after caching.
    """
    key = recipe_key(state, overrides)
    check = _check_cache.get(key)
    if check is not None:
        _check_cache.move_to_end(key)
        return check
    try:
        process = build_process(state, overrides=overrides)
    except Exception as exc:  # noqa: BLE001
        check = RecipeCheck(error=str(exc))
    else:
        check = RecipeCheck(
            error=None,
            units=tuple(process.flow_sheet.units_dict),
            species=tuple(process.component_system.species),
            signal_options=tuple(
                (label, tuple(target)) for label, target in measurable_signal_options(process)
            ),
            _process=process,
        )
    _check_cache[key] = check
    while len(_check_cache) > _CHECK_CACHE_SIZE:
        _check_cache.popitem(last=False)
    return check


def clear_recipe_checks() -> None:
    """Drop every memoized `RecipeCheck`."""
    _check_cache.clear()
