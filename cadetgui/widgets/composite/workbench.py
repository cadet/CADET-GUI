from __future__ import annotations

from typing import Dict, Optional

import ipywidgets as W

from .._chrome import logo_data_uri, style_tag
from .configuration import ConfigurationWidget
from .data_import import DataImportWidget
from .solution import SolutionWidget

__all__ = ["WorkbenchWidget"]

_STEPS = ("Configuration", "Simulation", "Experimental Data")


class WorkbenchWidget:
    """Top-level shell: a sidebar-navigated Configuration/Simulation/Data page.

    Builds and wires a `ConfigurationWidget`, `SolutionWidget`, and
    `DataImportWidget` together (same bindings as
    examples/configuration_and_solution.ipynb), showing exactly one at a time
    via a left sidebar instead of stacking all three inline. Each stays a
    plain attribute (`.configuration`/`.solution`/`.data`) for scripting —
    the shell is purely a navigation convenience, not a black box.
    """

    def __init__(
        self,
        *,
        configuration: Optional[ConfigurationWidget] = None,
        solution: Optional[SolutionWidget] = None,
        data: Optional[DataImportWidget] = None,
    ) -> None:
        self.configuration = configuration or ConfigurationWidget()
        self.solution = solution or SolutionWidget()
        self.data = data or DataImportWidget()

        self.solution.bind_to_config(self.configuration)
        self.solution.bind_to_data(self.data)

        self._panes: Dict[str, W.Widget] = {
            "Configuration": self.configuration.root,
            "Simulation": self.solution.root,
            "Experimental Data": self.data.root,
        }
        for root in self._panes.values():
            root.layout.display = "none"

        self._nav = W.ToggleButtons(options=list(_STEPS))
        self._nav.add_class("cadetgui-sidebar-nav")
        self._nav.observe(self._on_nav_change, names="index")

        self._content = W.VBox(list(self._panes.values()))
        self._content.add_class("cadetgui-workbench-content")

        top_bar = W.HTML(
            "<div class='cadetgui-topbar'>"
            f"<img src='{logo_data_uri()}' alt='CADET'>"
            "<span class='cadetgui-topbar-title'>Workbench</span>"
            "</div>"
        )
        body = W.HBox([self._nav, self._content])
        body.add_class("cadetgui-workbench-body")

        self.root = W.VBox([W.HTML(style_tag()), top_bar, body])
        self.root.add_class("cadetgui-panel")
        self.root.add_class("cadetgui-workbench")

        self._show(_STEPS[0])

    def _on_nav_change(self, change: dict) -> None:
        if change.get("name") != "index":
            return
        self._show(_STEPS[change["new"]])

    def _show(self, step: str) -> None:
        for name, root in self._panes.items():
            root.layout.display = "" if name == step else "none"

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
