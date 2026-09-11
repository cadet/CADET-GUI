from __future__ import annotations

from typing import Optional

import ipywidgets as W

from .._chrome import style_tag
from .data_import import DataImportWidget

__all__ = ["ParameterEstimationWidget"]


class ParameterEstimationWidget:
    """Parameter estimation: fit a process's parameters against experimental data.

    Currently just houses experimental-data import (`DataImportWidget`) as its
    first section -- the fitting workflow itself (PRODUCT_VISION.md §16) isn't
    built yet; `.data` is exposed directly for other widgets (e.g.
    `SolutionWidget.bind_to_data`) and scripting.
    """

    def __init__(self, *, data: Optional[DataImportWidget] = None) -> None:
        self.data = data or DataImportWidget()

        self.root = W.VBox(
            [
                W.HTML(style_tag()),
                W.HTML("<div class='cadetgui-panel-title'>Parameter estimation</div>"),
                self.data.root,
            ]
        )
        self.root.add_class("cadetgui-panel")

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
