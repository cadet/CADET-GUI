# =========================================
# File: cadetgui/widgets/composite/configuration.py
# =========================================
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import ipywidgets as W
from CADETProcess.processModel import ComponentSystem

from ...cadetprocessadapter import (
    DEFAULT_COLUMN_FACTORIES,
    MODEL_REGISTRY,
    build_column_config_spec,
)
from .._chrome import style_tag
from ..elements import ChoiceField
from ..forms import FormRenderer

__all__ = ["ConfigurationWidget"]


class ConfigurationWidget:
    """Pick a unit operation + model-builder template, configure both, build a process.

    Rebuilds its forms whenever the component count, column, or model selection
    changes. `.process` holds the latest successfully-built object; `add_listener`
    registers a callback that fires with it on every successful build.
    """

    def __init__(
        self,
        *,
        registry: Optional[Dict[str, Callable[[Any], Any]]] = None,
        columns: Optional[Dict[str, Callable[[ComponentSystem], Any]]] = None,
    ) -> None:
        self._registry = registry or MODEL_REGISTRY
        self._columns = columns or DEFAULT_COLUMN_FACTORIES
        self._column_cache: Dict[Any, Any] = {}
        self._listeners: List[Callable[[Any], None]] = []
        self.process: Any = None
        self._column_form: Optional[FormRenderer] = None
        self._model_form: Optional[FormRenderer] = None

        self._components = W.BoundedIntText(description="Components:", value=1, min=1, max=99)
        self._column_picker = ChoiceField(label="Column:", options=list(self._columns.items()))
        self._model_picker = ChoiceField(label="Model:", options=list(self._registry.items()))

        self._column_form_box = W.VBox([])
        self._model_form_box = W.VBox([])
        self.status = W.HTML("<em>Select a column and model.</em>")
        self.status.add_class("cadetgui-status")

        toolbar = W.HBox(
            [self._components, self._column_picker, self._model_picker],
            layout=W.Layout(flex_flow="row wrap"),
        )
        toolbar.add_class("cadetgui-toolbar")

        self.root = W.VBox(
            [
                W.HTML(style_tag()),
                W.HTML("<div class='cadetgui-panel-title'>Configuration</div>"),
                toolbar,
                self._column_form_box,
                self._model_form_box,
                self.status,
            ]
        )
        self.root.add_class("cadetgui-panel")

        self._components.observe(self._on_components_change, names="value")
        self._column_picker.observe(self._on_selection_change, names="selected_index")
        self._model_picker.observe(self._on_selection_change, names="selected_index")

        self._rebuild_forms()

    def add_listener(self, fn: Callable[[Any], None]) -> None:
        """Register a callback fired with `.process` on every successful build."""
        self._listeners.append(fn)

    def _notify(self) -> None:
        for fn in list(self._listeners):
            fn(self.process)

    def _get_column(self) -> Any:
        factory = self._column_picker.value
        if factory is None:
            return None
        if factory not in self._column_cache:
            cs = ComponentSystem(self._components.value)
            self._column_cache[factory] = factory(cs)
        return self._column_cache[factory]

    def _on_components_change(self, change: dict) -> None:
        if change.get("name") != "value":
            return
        self._column_cache.clear()
        self._rebuild_forms()

    def _on_selection_change(self, change: dict) -> None:
        if change.get("name") != "selected_index":
            return
        self._rebuild_forms()

    def _on_process_built(self, built: Any) -> None:
        self.process = built
        self._notify()
        self.status.value = "<em>Process built.</em>"

    def _rebuild_forms(self) -> None:
        column = self._get_column()
        model_fn = self._model_picker.value
        if column is None or model_fn is None:
            self._column_form_box.children = ()
            self._model_form_box.children = ()
            return

        self._column_form = FormRenderer(build_column_config_spec(column))
        self._column_form_box.children = (self._column_form.root,)

        self._model_form = FormRenderer(model_fn(column), on_built=self._on_process_built)
        self._model_form_box.children = (self._model_form.root,)

        self.status.value = "<em>Configure the column, then the model, and Apply each.</em>"

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
