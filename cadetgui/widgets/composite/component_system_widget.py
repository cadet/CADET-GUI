from __future__ import annotations

import json
from typing import Any, Callable, List, Sequence

import ipywidgets as W
from CADETProcess.processModel import ComponentSystem

from .._chrome import style_tag
from ..elements import ComponentListField
from ._code_view import CodeView

__all__ = ["ComponentSystemWidget"]


class ComponentSystemWidget:
    """Define the components of a model by name; `component_system` is the object.

    The object is updated in place, so units, flow sheets and processes made with it follow
    the names.
    """

    def __init__(self, names: Sequence[str] = ()) -> None:
        self._listeners: List[Callable[[Any], None]] = []
        self.field = ComponentListField(label="Components:", value=list(names), blank_rows=True)
        self._component_system = ComponentSystem(list(names))
        self.code_view = CodeView(self.code)
        self.root = W.VBox([
            W.HTML(style_tag()),
            W.HTML("<div class='cadetgui-panel-title'>Component system</div>"),
            self.field,
            self.code_view.root,
        ])
        self.root.add_class("cadetgui-panel")
        self.field.observe(lambda _change: self._changed(), names="value")

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

    def _changed(self) -> None:
        for component in list(self._component_system.components):
            self._component_system.remove_component(component)
        for name in self.names:
            self._component_system.add_component(name)
        self.code_view.refresh()
        for fn in list(self._listeners):
            fn(self.names)

    def add_listener(self, fn: Callable[[Any], None]) -> None:
        """Call `fn(names)` whenever the components change."""
        self._listeners.append(fn)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
