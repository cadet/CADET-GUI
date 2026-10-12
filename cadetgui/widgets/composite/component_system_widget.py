from __future__ import annotations

import json
from typing import Any, Callable, List, Optional

import ipywidgets as W
from CADETProcess.processModel import ComponentSystem

from .._chrome import style_tag
from ..elements import ComponentListField
from ._code_view import CodeView
from ._model_sync import changed, watch

__all__ = ["ComponentSystemWidget"]


class ComponentSystemWidget:
    """Define the components of a ComponentSystem by name.

    The ComponentSystem is edited in place, so units, flow sheets and processes made with
    it follow the names. Without one, an empty ComponentSystem is created.
    """

    def __init__(self, component_system: Optional[ComponentSystem] = None) -> None:
        self._listeners: List[Callable[[Any], None]] = []
        self._component_system = (
            ComponentSystem() if component_system is None else component_system
        )
        self.field = ComponentListField(
            label="Components:", value=list(self._component_system.names), blank_rows=True
        )
        self.code_view = CodeView(self.code)
        self.root = W.VBox([
            W.HTML(style_tag()),
            W.HTML("<div class='cadetgui-panel-title'>Component system</div>"),
            self.field,
            self.code_view.root,
        ])
        self.root.add_class("cadetgui-panel")
        self.field.observe(lambda _change: self._changed(), names="value")
        watch(self._component_system, self)

    @property
    def names(self) -> List[str]:
        """The component names, in order; rows without a name are left out."""
        return [name.strip() for name in self.field.value if name.strip()]

    @property
    def component_system(self) -> ComponentSystem:
        """The ComponentSystem with the current component names."""
        return self._component_system

    def get_value(self) -> ComponentSystem:
        """Return the ComponentSystem with the current component names."""
        return self._component_system

    def code(self) -> str:
        """Return the CADET-Process code that creates this component system."""
        return (
            "from CADETProcess.processModel import ComponentSystem\n\n"
            f"component_system = ComponentSystem([{', '.join(map(json.dumps, self.names))}])"
        )

    def refresh(self) -> None:
        """Show the current components, e.g. after they were changed in code."""
        if self.names != list(self._component_system.names):
            self.field.value = list(self._component_system.names)
        self.code_view.refresh()

    def _changed(self) -> None:
        if self.names != list(self._component_system.names):
            for component in list(self._component_system.components):
                self._component_system.remove_component(component)
            for name in self.names:
                self._component_system.add_component(name)
        self.code_view.refresh()
        changed(self._component_system, self)
        for fn in list(self._listeners):
            fn(self.names)

    def add_listener(self, fn: Callable[[Any], None]) -> None:
        """Call `fn(names)` whenever the components change."""
        self._listeners.append(fn)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
