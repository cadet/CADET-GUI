from __future__ import annotations

import ast
from typing import Any, Callable, List, Optional, Tuple

import ipywidgets as W
import numpy as np
from CADETProcess import CADETProcessError

from .._status import status_html
from ..elements import ChoiceField, SelectableTable, TextField
from ._parameter_values import _number_text
from ._polynomial_editor import PolynomialEditor

__all__ = ["EventEditor", "compact_state", "event_paths", "rounded_state", "state_text"]

_COLUMNS = ["Time / s", "Event", "Unit", "Parameter", "Value"]


def event_paths(process: Any) -> List[Tuple[str, str]]:
    """`(label, path)` of every parameter an event of `process` can change."""
    flow_sheet = process.flow_sheet
    paths = [
        (f"{unit.name} · {name}", f"flow_sheet.{unit.name}.{name}")
        for unit in flow_sheet.units
        for name in unit.section_dependent_parameters
    ]
    output_states = flow_sheet.section_dependent_parameters["output_states"]
    paths += [
        (f"{name} · outlet split", f"flow_sheet.output_states.{name}")
        for name, state in output_states.items()
        if len(state) > 1
    ]
    return paths


def _round(x: float) -> float | int:
    rounded = float(f"{x:.6g}")
    return int(rounded) if rounded.is_integer() else rounded


def compact_state(coefficients: Any) -> Any:
    """Shortest event state for polynomial coefficients: `[[1, 0, 0, 0]]` becomes `[1]`."""
    rows = np.atleast_2d(np.asarray(coefficients, dtype=float))
    trimmed = [np.trim_zeros(row, "b").tolist() or [0.0] for row in rows]
    trimmed = [[_round(x) for x in row] for row in trimmed]
    if all(len(row) == 1 for row in trimmed):
        constants = [row[0] for row in trimmed]
        return constants[0] if np.ndim(coefficients) == 1 else constants
    return trimmed[0] if np.ndim(coefficients) == 1 else trimmed


def rounded_state(state: Any) -> Any:
    """Return the state as a plain Python value with numbers rounded, for showing it."""
    value = state.tolist() if isinstance(state, np.ndarray) else state
    if isinstance(value, float):
        return _round(value)
    if isinstance(value, list):
        return [rounded_state(v) for v in value]
    return value


def _polynomial_text(coefficients: Any) -> str:
    terms = ["", "·Δt", "·Δt²", "·Δt³"]
    parts = [
        (value, f"{_number_text(abs(_round(value)))}{term}")
        for value, term in zip(coefficients, terms)
        if value != 0
    ]
    if not parts:
        return "0"
    text = ("−" if parts[0][0] < 0 else "") + parts[0][1]
    for value, part in parts[1:]:
        text += (" − " if value < 0 else " + ") + part
    return text


def _where(path: str) -> Tuple[str, str]:
    _flow_sheet, owner, parameter = path.split(".")
    return (parameter, "outlet split") if owner == "output_states" else (owner, parameter)


def state_text(process: Any, event: Any) -> str:
    """Describe an event's state in words: a profile like `0.0167·Δt`, per component for `c`."""
    _flow_sheet, owner, parameter = event.parameter_path.split(".")
    if owner == "output_states":
        unit = process.flow_sheet[parameter]
        destinations = process.flow_sheet.connections[unit]["destinations"][None]
        return ", ".join(
            f"{destination.name}: {_number_text(_round(share))}"
            for destination, share in zip(destinations, event.full_state)
        )
    unit = process.flow_sheet[owner]
    if parameter not in getattr(unit, "polynomial_parameters", {}):
        return repr(rounded_state(event.state))
    rows = np.reshape(event.full_state, (-1, 4))
    names = unit.component_system.names
    if parameter != "c" or len(names) == 1:
        return _polynomial_text(rows[0])
    return "; ".join(f"{name}: {_polynomial_text(row)}" for name, row in zip(names, rows))


class EventEditor:
    """The events of a process as a table (`table`); a row opens the event in `controls`.

    The state of a polynomial parameter (an inlet's `c` or `flow_rate`) is edited by its
    coefficients and drawn until the next event of that parameter.
    """

    def __init__(self, process: Any, on_change: Callable[[], None]) -> None:
        self.process = process
        self._on_change = on_change
        self.table = SelectableTable(label="Events", columns=_COLUMNS, empty_text="No events yet.")
        self.new = W.Button(description="New event", icon="plus")
        self.title = W.HTML()
        self.name = TextField(label="name")
        self.path = ChoiceField(label="parameter")
        self.time = TextField(label="time", units=r"\mathrm{s}", help="When the event happens.")
        self.value = TextField(label="value")
        self._state = W.VBox()
        self.apply = W.Button(description="Add event", icon="check")
        self.remove = W.Button(description="Remove event", icon="trash")
        self.status = W.HTML()
        self.editors: List[PolynomialEditor] = []
        self._scratch: Optional[Any] = None
        self.form = W.VBox([
            self.title, self.name, self.path, self.time, self._state,
            W.HBox([self.apply, self.remove]), self.status,
        ])
        self.controls = W.VBox([self.new, self.form])
        self.table.observe(lambda _change: self._load(), names="selected_index")
        self.path.observe(lambda _change: self._show_state(), names="selected_index")
        self.time.observe(lambda _change: self._show_state(), names="value")
        self.new.on_click(lambda _button: self._select(None))
        self.apply.on_click(lambda _button: self._apply())
        self.remove.on_click(lambda _button: self._remove())
        self.refresh()

    def refresh(self, select: Optional[str] = None) -> None:
        """Show the current events and parameter paths, e.g. after events changed in code."""
        events = sorted(self.process.events, key=lambda e: e.time)
        names = [e.name for e in events]
        selected = select if select is not None else self.table.value
        rows = [
            [_number_text(e.time), e.name, *_where(e.parameter_path), state_text(self.process, e)]
            for e in events
        ]
        self.table.set_options([(name, name) for name in names], rows=rows, select_none=True)
        self.path.set_options(event_paths(self.process))
        self.table.value = selected if selected in names else None
        self._load()

    def _select(self, name: Optional[str]) -> None:
        self.table.value = name
        self._load()

    def _event(self) -> Optional[Any]:
        name = self.table.value
        return None if name is None else self.process.events_dict[name]

    def _load(self) -> None:
        event = self._event()
        title = "New event" if event is None else f"Event · {event.name}"
        self.title.value = f"<div class='cadetgui-section-title'>{title}</div>"
        self.apply.description = "Add event" if event is None else "Save changes"
        self.remove.layout.display = "none" if event is None else ""
        self.status.value = ""
        if event is None:
            self.name.value = ""
            self.time.value = "0"
        else:
            self.name.value = event.name
            self.time.value = _number_text(event.time)
            self.path.value = event.parameter_path
        self._show_state()

    def _unit_and_parameter(self) -> tuple[Optional[Any], str]:
        parts = (self.path.value or "").split(".")
        if len(parts) != 3 or parts[1] == "output_states":
            return None, parts[-1]
        return self.process.flow_sheet[parts[1]], parts[2]

    def _duration(self) -> float:
        try:
            start = float(self.time.value)
        except ValueError:
            start = 0.0
        later = [
            e.time for e in self.process.events
            if e.parameter_path == self.path.value and e.time > start and e.name != self.name.value
        ]
        return max(min(later, default=float(self.process.cycle_time)) - start, 1.0)

    def _show_state(self) -> None:
        unit, parameter = self._unit_and_parameter()
        event = self._event()
        own_event = event is not None and event.parameter_path == self.path.value
        if unit is None or parameter not in getattr(unit, "polynomial_parameters", {}):
            self._scratch = None
            self.editors = []
            state = event.state if own_event else getattr(unit, parameter, None)
            self.value.value = "" if state is None else repr(rounded_state(state))
            self._state.children = [self.value]
            return
        self._scratch = type(unit)(unit.component_system, unit.name)
        setattr(self._scratch, parameter, getattr(unit, parameter))
        if own_event:
            shape = np.shape(getattr(unit, parameter))
            setattr(self._scratch, parameter, np.reshape(event.full_state, shape).tolist())
        indices = range(unit.n_comp) if parameter == "c" else [None]
        self.editors = [
            PolynomialEditor(
                self._scratch, parameter, index, duration=self._duration(), start="the event"
            )
            for index in indices
        ]
        self._state.children = [editor.root for editor in self.editors]

    def _state_value(self) -> Any:
        if self._scratch is not None:
            _unit, parameter = self._unit_and_parameter()
            return compact_state(getattr(self._scratch, parameter))
        return ast.literal_eval(self.value.value)

    def _apply(self) -> None:
        event = self._event()
        name = self.name.value.strip()
        try:
            state = self._state_value()
            time = float(self.time.value)
        except (ValueError, SyntaxError):
            self.status.value = status_html("warn", "Enter a number for the time and the value.")
            return
        if not name:
            self.status.value = status_html("warn", "Give the event a name.")
            return
        if event is not None:
            self.process.remove_event(event.name)
        try:
            self.process.add_event(name, self.path.value, state, time)
        except (CADETProcessError, ValueError, TypeError) as exc:
            if event is not None:
                self.process.add_event(
                    event.name, event.parameter_path, event.full_state, event.time
                )
            self.status.value = status_html("warn", str(exc))
            return
        self.refresh(select=name)
        self._on_change()

    def _remove(self) -> None:
        event = self._event()
        if event is None:
            return
        self.process.remove_event(event.name)
        self.refresh()
        self._on_change()
