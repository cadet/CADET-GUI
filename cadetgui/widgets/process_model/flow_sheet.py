from __future__ import annotations

from html import escape
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple

import ipywidgets as W
from CADETProcess import CADETProcessError
from CADETProcess.processModel import Inlet, Outlet

from ..base import Widget
from ..diagrams.flow_sheet import flow_sheet_edges, render_flow_sheet_svg
from ..elements import ChoiceField
from ..ui.html import status_html
from ..ui.layout import CodeView, panel
from .sync import changed, watch
from .unit_operations import UnitOperationWidget
from .values import components_html

__all__ = ["FlowSheetWidget"]


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
        for origin, destination in flow_sheet_edges(self.flow_sheet):
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


class FlowSheetWidget(Widget):
    """Diagram of a CADET-Process FlowSheet, with a chosen unit's view below it.

    Units with missing parameters are marked in the diagram. Given `units` (a list of unit
    operations, or a dict of name: unit operation), it also adds units and connects them;
    `connections` (pairs of unit names) are made right away, adding their units. Without
    `units`, a chosen unit's parameters are shown below the diagram. Listeners get the flow
    sheet after every edit made here.
    """

    def __init__(
        self,
        flow_sheet: Any,
        units: Any = None,
        connections: Sequence[Tuple[str, str]] = (),
    ) -> None:
        super().__init__()
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
        children = [self._components, self.diagram]
        if self.controls is not None:
            children += [self.controls.root, self.code_view.root]
        else:
            children += [self.unit_picker, self._panel]
        self.root = panel(f"Flow sheet · {title}", *children)
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
        self._notify(self.flow_sheet)

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
            for origin, destination in flow_sheet_edges(self.flow_sheet)
        ]
        return "\n".join(lines)

    def get_value(self) -> Any:
        """Return the FlowSheet this widget shows."""
        return self.flow_sheet
