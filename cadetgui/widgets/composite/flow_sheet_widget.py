from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import ipywidgets as W
from CADETProcess import CADETProcessError
from CADETProcess.processModel import Cstr, Inlet, Outlet, TubularReactor
from CADETProcess.processModel.unitOperation import ChromatographicColumnBase

from .._chrome import style_tag
from .._status import status_html
from ..elements import ChoiceField
from ._code_view import CodeView
from ._model_sync import changed, watch
from ._parameter_values import components_html
from ._pid_symbols import FG, MUTED, MUTED_STROKE, load_symbol
from .system_diagram import _PORTS, _caption, _marker, _symbol, _tube, _wire
from .unit_operation_widget import UnitOperationWidget

__all__ = ["FlowSheetWidget", "render_flow_sheet_svg"]

_MARGIN = 16
_GAP = 70
_ROW = 70
_BOX = (130.0, 60.0)
_TUBE_LENGTH = 90.0
_LEAD = 16
WARN = "var(--cg-warn, #a16207)"


@dataclass
class _Node:
    unit: Any
    symbol: Optional[str]
    width: float
    up: float
    down: float
    in_x: float
    out_x: float
    x: float = 0.0
    y: float = 0.0


def _node(unit: Any) -> _Node:
    if isinstance(unit, ChromatographicColumnBase):
        name = "Column"
    elif isinstance(unit, Inlet):
        name = "Inlet"
    elif isinstance(unit, Outlet):
        name = "Outlet"
    elif isinstance(unit, Cstr):
        name = "Mixer"
    elif isinstance(unit, TubularReactor):
        return _Node(unit, None, _TUBE_LENGTH, 0.0, 0.0, 0.0, _TUBE_LENGTH)
    else:
        w, h = _BOX
        return _Node(unit, None, w, h / 2, h / 2, 0.0, w)
    sym = load_symbol(name)
    in_x, out_x, port_y = _PORTS[name]
    return _Node(unit, name, sym.width, port_y, sym.height - port_y, in_x, out_x)


def _edges(flow_sheet: Any) -> List[Tuple[Any, Any]]:
    edges = []
    for origin, entry in flow_sheet.connections.items():
        for destinations in (entry["destinations"] or {}).values():
            edges.extend((origin, destination) for destination in destinations)
    return list(dict.fromkeys(edges))


def _layers(units: List[Any], edges: List[Tuple[Any, Any]]) -> Dict[Any, int]:
    """Longest-path layer of every unit; edges closing a cycle are ignored."""
    successors: Dict[Any, List[Any]] = {u: [] for u in units}
    for origin, destination in edges:
        successors[origin].append(destination)
    order: List[Any] = []
    state: Dict[Any, int] = {}
    forward = set()

    def visit(unit: Any) -> None:
        state[unit] = 1
        for nxt in successors[unit]:
            if state.get(nxt) is None:
                forward.add((unit, nxt))
                visit(nxt)
            elif state[nxt] == 2:
                forward.add((unit, nxt))
        state[unit] = 2
        order.append(unit)

    has_origin = {d for _, d in edges}
    for unit in [u for u in units if u not in has_origin] + units:
        if state.get(unit) is None:
            visit(unit)

    layer = {u: 0 for u in units}
    for unit in reversed(order):
        for nxt in successors[unit]:
            if (unit, nxt) in forward:
                layer[nxt] = max(layer[nxt], layer[unit] + 1)

    # Unconnected units are lined up after the connected ones, in the order they were added.
    connected = {u for edge in edges for u in edge}
    first_free = max((layer[u] for u in connected), default=-1) + 1
    for offset, unit in enumerate(u for u in units if u not in connected):
        layer[unit] = first_free + offset
    return layer


def render_flow_sheet_svg(flow_sheet: Any) -> str:
    """Draw the units and connections of any CADET-Process FlowSheet, left to right."""
    units = list(flow_sheet.units)
    if not units:
        return f'<em style="color:{MUTED}">The flow sheet has no units yet.</em>'
    edges = _edges(flow_sheet)
    layer = _layers(units, edges)
    nodes = {u: _node(u) for u in units}

    columns: Dict[int, List[_Node]] = {}
    for unit in units:
        columns.setdefault(layer[unit], []).append(nodes[unit])

    # Units in the same row share one flow line, so straight connections stay straight.
    caption_h = 3 * _LEAD + 8
    n_rows = max(len(c) for c in columns.values())
    up = [max(c[r].up for c in columns.values() if r < len(c)) for r in range(n_rows)]
    down = [max(c[r].down for c in columns.values() if r < len(c)) for r in range(n_rows)]
    row_y = []
    y = _MARGIN
    for r in range(n_rows):
        row_y.append(y + up[r])
        y = row_y[r] + down[r] + caption_h + _ROW
    bottom = y - _ROW

    x = _MARGIN
    for index in sorted(columns):
        column = columns[index]
        width = max(n.width for n in column)
        for r, node in enumerate(column):
            node.x = x + (width - node.width) / 2
            node.y = row_y[r]
        x += width + _GAP
    width = x - _GAP + _MARGIN

    parts = [_marker("cg-arrow", FG), _marker("cg-arrow-muted", MUTED_STROKE)]
    loop_y = bottom + 12
    for origin, destination in edges:
        a, b = nodes[origin], nodes[destination]
        x1, y1 = a.x + a.out_x, a.y
        x2, y2 = b.x + b.in_x, b.y
        if layer[destination] > layer[origin]:
            xm = x2 - _GAP / 2
            d = f"M{x1:g} {y1:g} H{xm:g} V{y2:g} H{x2:g}"
        else:
            d = f"M{x1:g} {y1:g} h12 V{loop_y:g} H{x2 - 12:g} V{y2:g} H{x2:g}"
            loop_y += 10
        parts.append(_wire(d))
    bottom = max(bottom, loop_y)

    for node in nodes.values():
        cx = node.x + node.width / 2
        if isinstance(node.unit, Cstr):
            symbol = _symbol(node.symbol, node.x, node.y - node.up)
            parts.append(symbol.replace(">Mixer<", ">CSTR<"))
        elif node.symbol is not None:
            parts.append(_symbol(node.symbol, node.x, node.y - node.up))
        elif isinstance(node.unit, TubularReactor):
            parts.append(_tube(node.x, node.x + node.width, node.y))
        else:
            w, h = _BOX
            parts.append(
                f'<rect x="{node.x:g}" y="{node.y - h / 2:g}" width="{w:g}" height="{h:g}" '
                f'rx="6" fill="none" style="stroke: {FG}" stroke-width="1.5"/>'
            )
        top = node.y + node.down + 18
        parts.append(_caption([node.unit.name], cx, top, strong=True))
        parts.append(_caption([type(node.unit).__name__], cx, top + _LEAD))
        missing = len(getattr(node.unit, "missing_parameters", []))
        if missing:
            label = f"{missing} missing parameter{'s' if missing > 1 else ''}"
            parts.append(
                f'<text x="{cx:g}" y="{top + 2 * _LEAD:g}" text-anchor="middle" font-size="14" '
                f'style="fill: {WARN}">{label}</text>'
            )

    height = bottom + _MARGIN
    return (
        f'<div class="cadetgui-system-diagram">'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'role="img" aria-label="Flow sheet {escape(str(flow_sheet.name))}" '
        f'style="width:100%;max-width:{width:.0f}px;height:auto;display:block" '
        f'font-family="var(--cg-font, system-ui, sans-serif)">'
        f'{"".join(parts)}</svg></div>'
    )


def _units_of(units: Any) -> List[Any]:
    return list(units.values() if isinstance(units, Mapping) else units)


class _BuildControls:
    """Add units to a flow sheet, connect them, and undo either."""

    def __init__(self, flow_sheet: Any, units: Any, on_change: Callable[[], None]) -> None:
        self.flow_sheet = flow_sheet
        self._units = units
        self._on_change = on_change
        self.unit_picker = ChoiceField(label="Unit to add:", options=[])
        self.add_button = W.Button(
            description="Add to flow sheet", icon="plus", layout=W.Layout(width="180px")
        )
        self.origin_picker = ChoiceField(label="From:", options=[])
        self.destination_picker = ChoiceField(label="To:", options=[])
        self.connect_button = W.Button(description="Connect", icon="arrow-right")
        self.status = W.HTML()
        self._added = W.VBox()
        self.root = W.VBox([
            W.HTML("<div class='cadetgui-section-title'>Build</div>"),
            self.unit_picker,
            self.add_button,
            self.origin_picker,
            self.destination_picker,
            self.connect_button,
            self.status,
            self._added,
        ])
        self.add_button.on_click(lambda _button: self.add())
        self.connect_button.on_click(lambda _button: self.connect())

    def _available(self) -> List[Any]:
        return [u for u in _units_of(self._units) if u not in self.flow_sheet.units]

    def refresh(self) -> None:
        """Offer the units not yet added, and every possible connection."""
        self.unit_picker.set_options([(u.name, u) for u in self._available()], keep_value=True)
        units = list(self.flow_sheet.units)
        origins = [(u.name, u) for u in units if not isinstance(u, Outlet)]
        destinations = [(u.name, u) for u in units if not isinstance(u, Inlet)]
        self.origin_picker.set_options(origins, keep_value=True)
        self.destination_picker.set_options(destinations, keep_value=True)
        self._added.children = self._rows()

    def _rows(self) -> List[W.Widget]:
        rows: List[W.Widget] = []
        for unit in self.flow_sheet.units:
            rows.append(self._row(
                f"<code class='cadetgui-param-label'>{escape(unit.name)}</code>",
                f"Remove {unit.name} and its connections from the flow sheet",
                lambda unit=unit: self.flow_sheet.remove_unit(unit),
            ))
        for origin, destination in _edges(self.flow_sheet):
            rows.append(self._row(
                f"<code class='cadetgui-param-label'>{escape(origin.name)} → "
                f"{escape(destination.name)}</code>",
                f"Remove the connection {origin.name} → {destination.name}",
                lambda o=origin, d=destination: self.flow_sheet.remove_connection(o, d),
            ))
        return rows

    def _row(self, label: str, tooltip: str, remove: Callable[[], None]) -> W.HBox:
        button = W.Button(description="✕", tooltip=tooltip, layout=W.Layout(width="36px"))
        button.on_click(lambda _button: self._run(remove))
        return W.HBox([button, W.HTML(label)])

    def _run(self, action: Callable[[], None]) -> None:
        try:
            action()
        except (CADETProcessError, ValueError, TypeError) as exc:
            self.status.value = status_html("error", str(exc))
            return
        self.status.value = ""
        self._on_change()

    def add(self) -> None:
        """Add the selected unit to the flow sheet."""
        if self.unit_picker.value is not None:
            self._run(lambda: self.flow_sheet.add_unit(self.unit_picker.value))

    def connect(self) -> None:
        """Connect the selected origin to the selected destination."""
        origin, destination = self.origin_picker.value, self.destination_picker.value
        if origin is not None and destination is not None:
            self._run(lambda: self.flow_sheet.add_connection(origin, destination))


class FlowSheetWidget:
    """Diagram of a CADET-Process FlowSheet, with a chosen unit's view below it.

    Units with missing parameters are marked in the diagram. Given `units` (a list of unit
    operations, or a dict of name: unit operation), it also adds units and connects them;
    `connections` (pairs of unit names) are made right away, adding their units. Without
    `units`, a chosen unit's parameters are shown below the diagram.
    """

    def __init__(
        self,
        flow_sheet: Any,
        units: Any = None,
        connections: Sequence[Tuple[str, str]] = (),
    ) -> None:
        self.flow_sheet = flow_sheet
        if connections:
            available = {u.name: u for u in _units_of(units)}
            for pair in connections:
                for name in pair:
                    if available[name] not in flow_sheet.units:
                        flow_sheet.add_unit(available[name])
                flow_sheet.add_connection(available[pair[0]], available[pair[1]])
        self.diagram = W.HTML()
        self._components = W.HTML()
        self.unit_picker = ChoiceField(label="Show unit:", options=[])
        self.unit_view: Optional[UnitOperationWidget] = None
        self._panel = W.VBox()
        self.controls = None if units is None else _BuildControls(flow_sheet, units, self._edited)
        self.code_view = CodeView(self.code)
        title = escape(str(flow_sheet.name))
        children = [
            W.HTML(style_tag()),
            W.HTML(f"<div class='cadetgui-panel-title'>Flow sheet · {title}</div>"),
            self._components,
            self.diagram,
        ]
        if self.controls is not None:
            children += [self.controls.root, self.code_view.root]
        else:
            children += [self.unit_picker, self._panel]
        self.root = W.VBox(children)
        self.root.add_class("cadetgui-panel")
        self.unit_picker.observe(lambda _change: self._show_unit(), names="selected_index")
        watch(flow_sheet.component_system, self)
        self.refresh()

    def refresh(self) -> None:
        """Redraw, e.g. after units, connections or parameters were changed in code."""
        self._components.value = components_html(self.flow_sheet.component_system)
        self.diagram.value = render_flow_sheet_svg(self.flow_sheet)
        units = list(self.flow_sheet.units)
        selected = self.unit_picker.value
        self.unit_picker.set_options([(u.name, u) for u in units], keep_value=True)
        if selected not in units and units:
            missing = [u for u in units if u.missing_parameters]
            self.unit_picker.value = (missing or units)[0]
        self.unit_picker.layout.display = "" if units else "none"
        self._show_unit()
        if self.controls is not None:
            self.controls.refresh()
        self.code_view.refresh()

    def _edited(self) -> None:
        self.refresh()
        changed(self.flow_sheet.component_system, self)

    def _show_unit(self) -> None:
        if self.controls is not None:
            return
        unit = self.unit_picker.value
        self.unit_view = None if unit is None else UnitOperationWidget(unit)
        self._panel.children = [] if self.unit_view is None else [self.unit_view.root]

    def code(self) -> str:
        """Return the CADET-Process code that builds this flow sheet from its units."""
        lines = [
            "from CADETProcess.processModel import FlowSheet",
            "",
            f'flow_sheet = FlowSheet(component_system, "{self.flow_sheet.name}")',
        ]
        lines += [f"flow_sheet.add_unit({unit.name})" for unit in self.flow_sheet.units]
        lines += [
            f"flow_sheet.add_connection({origin.name}, {destination.name})"
            for origin, destination in _edges(self.flow_sheet)
        ]
        return "\n".join(lines)

    def get_value(self) -> Any:
        """Return the FlowSheet this widget shows."""
        return self.flow_sheet

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
