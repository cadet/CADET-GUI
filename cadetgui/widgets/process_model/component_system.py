from __future__ import annotations

import json
from typing import List, Optional

from CADETProcess.processModel import ComponentSystem

from ..base import Widget
from ..elements import ComponentListField
from ..ui.layout import CodeView, panel
from .sync import changed, watch

__all__ = ["ComponentSystemWidget"]


class ComponentSystemWidget(Widget):
    """Define the components of a ComponentSystem by name.

    The ComponentSystem is edited in place, so units, flow sheets and processes made with
    it follow the names. Without one, an empty ComponentSystem is created.
    """

    def __init__(self, component_system: Optional[ComponentSystem] = None) -> None:
        super().__init__()
        self._component_system = (
            ComponentSystem() if component_system is None else component_system
        )
        self.field = ComponentListField(
            label="Components:", value=list(self._component_system.names), blank_rows=True
        )
        self.code_view = CodeView(self.code)
        self.root = panel("Component system", self.field, self.code_view.root)
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
        self._notify(self.names)
