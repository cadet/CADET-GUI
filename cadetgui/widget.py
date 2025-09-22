from __future__ import annotations

import io
import traceback
import ipywidgets as W
from abc import ABC, abstractmethod
from contextlib import redirect_stdout, redirect_stderr
from typing import Optional, Mapping, Callable, Any, Union, Dict, List
from .simulation import run_process as _default_runner

from .cadetprocessadapter import (
    ModelSpec,
    MODEL_REGISTRY,
    DEFAULT_COLUMN_FACTORIES,
    column_spec_from_required,
)
from CADETProcess.processModel import ComponentSystem

__all__ = [
    "BaseWidget",
    "Element",
    "TextField",
    "FloatField",
    "BoolField",
    "Display",
    "Popup",
    "ChoiceField",
    "ObjectChoiceField",
    "ProcessBuilderForm",
    "ConfigurationWidget",
    "SolutionWidget",
]

# =========================
# Base + small UI elements
# =========================
class BaseWidget(ABC):
    """Base widget container with a header, body, and status bar."""

    def __init__(self, *, title: Optional[str] = None) -> None:
        self.title = title or self.__class__.__name__
        self._status = W.HTML("<em>Ready.</em>")
        self._header = W.HTML(f"<h3 style='margin:0'>{self.title}</h3>")
        self._body = self._build_body()
        self.root = W.VBox([self._header, self._body, self._status])
        self._wire_events()

    @abstractmethod
    def _build_body(self) -> W.Widget:
        """Create and return the main widget body."""

    def _wire_events(self) -> None:
        """Connect event handlers (optional override)."""

    def set_status(self, text: str) -> None:
        self._status.value = text

    def display(self) -> None:
        from IPython.display import display as _display
        _display(self.root)


class Element(ABC):
    """Base class for small reusable form elements."""

    widget: W.Widget

    def get_value(self) -> object:
        raise NotImplementedError

    def set_value(self, value: object) -> None:
        raise NotImplementedError


class TextField(Element):
    def __init__(self, *, label: str = "", value: str = "") -> None:
        self.widget = W.Text(description=label, value=value)

    def get_value(self) -> str:
        return self.widget.value  # type: ignore[return-value]

    def set_value(self, value: object) -> None:
        self.widget.value = str(value)


class FloatField(Element):
    def __init__(self, *, label: str = "", value: float = 0.0) -> None:
        self.widget = W.FloatText(description=label, value=float(value))

    def get_value(self) -> float:
        return float(self.widget.value)  # type: ignore[return-value]

    def set_value(self, value: object) -> None:
        self.widget.value = float(value)  # type: ignore[assignment]


class BoolField(Element):
    def __init__(self, *, label: str = "", value: bool = False) -> None:
        self.widget = W.Checkbox(description=label, value=bool(value))

    def get_value(self) -> bool:
        return bool(self.widget.value)  # type: ignore[return-value]

    def set_value(self, value: object) -> None:
        self.widget.value = bool(value)  # type: ignore[assignment]


class Display(Element):
    def __init__(self, *, html: str = "") -> None:
        self.widget = W.HTML(value=html)


class Popup(Element):
    def __init__(self, *, title: str = "Info", content: W.Widget | None = None) -> None:
        body = content or W.HTML("<em>Empty</em>")
        acc = W.Accordion(children=[body])
        acc.set_title(0, title)
        acc.selected_index = None
        self.widget = acc

    def open(self) -> None:
        self.widget.selected_index = 0  # type: ignore[attr-defined]

    def close(self) -> None:
        self.widget.selected_index = None  # type: ignore[attr-defined]


class ChoiceField(Element):
    """Dropdown for selecting one option from a list of (label, value) pairs."""

    def __init__(self, *, label: str = "", options: list[tuple[str, object]] | None = None) -> None:
        self.widget = W.Dropdown(description=label, options=options or [])

    def get_value(self) -> object:
        return self.widget.value  # type: ignore[attr-defined, return-value]

    def set_value(self, value: object) -> None:
        self.widget.value = value  # type: ignore[attr-defined]


class ObjectChoiceField(ChoiceField):
    """Dropdown for arbitrary objects with a label function (or attribute)."""

    def __init__(
        self,
        *,
        label: str = "Select:",
        items: list[object] | dict[str, object],
        label_fn: Optional[Callable[[object], str]] = None,
        fallback_attr: str = "name",
    ) -> None:
        pairs: list[tuple[str, object]] = []
        if isinstance(items, dict):
            pairs = [(k, v) for k, v in items.items()]
        else:
            for obj in items:
                if label_fn is not None:
                    pairs.append((str(label_fn(obj)), obj))
                else:
                    disp = getattr(obj, fallback_attr, obj.__class__.__name__)
                    pairs.append((str(disp), obj))
        super().__init__(label=label, options=pairs)


# ===========================
# ProcessBuilderForm (was SpecDrivenConfig)
# ===========================
class ProcessBuilderForm(BaseWidget):
    """
    Render a ModelSpec into a form. On Apply, call spec.build(values) and
    store the result (e.g., a Process or a mutated Column) in `self.built`.
    """

    def __init__(self, spec: ModelSpec, *, title: Optional[str] = None) -> None:
        self._spec = spec
        self._widgets: Dict[str, W.Widget] = {}
        self._btn_apply = W.Button(description="Apply", button_style="success")
        self._btn_reset = W.Button(description="Reset")
        self.built: Any = None
        super().__init__(title=title or spec.title)

    def _field_widget(self, f) -> W.Widget:
        kind = f.kind
        default = f.default
        desc = f.label or f.name

        if kind == "float":
            return W.FloatText(description=desc, value=float(default) if default is not None else 0.0)
        if kind == "float_list":
            init = ", ".join(map(str, default)) if isinstance(default, (list, tuple)) else (str(default) if default is not None else "")
            return W.Textarea(description=desc, value=init, layout=W.Layout(width="100%"))
        if kind == "bool":
            return W.Checkbox(description=desc, value=bool(default))
        return W.Text(description=desc, value=str(default) if default is not None else "")

    def _build_body(self) -> W.Widget:
        rows: list[W.Widget] = []
        for f in self._spec.fields:
            w = self._field_widget(f)
            self._widgets[f.name] = w
            rows.append(w)
        actions = W.HBox([self._btn_apply, self._btn_reset])
        return W.VBox(rows + [actions])

    def _wire_events(self) -> None:
        self._btn_apply.on_click(self._on_apply)
        self._btn_reset.on_click(self._on_reset)

    def _collect_values(self) -> Dict[str, Any]:
        vals: Dict[str, Any] = {}
        for f in self._spec.fields:
            raw = getattr(self._widgets[f.name], "value", None)
            v = raw
            if f.transform is not None:
                v = f.transform(v)
            if f.validate is not None:
                f.validate(v)
            vals[f.name] = v
        return vals

    def _on_apply(self, _btn) -> None:
        try:
            v = self._collect_values()
            if self._spec.build is None:
                raise RuntimeError("Spec has no 'build' function.")
            self.built = self._spec.build(v)
            self.set_status("<em>Built successfully.</em>")
        except Exception as e:
            self.built = None
            self.set_status(f"<span style='color:#b00'>Error: {e}</span>")

    def _on_reset(self, _btn) -> None:
        for f in self._spec.fields:
            w = self._widgets[f.name]
            default = f.default
            try:
                if f.kind == "float":
                    w.value = float(default) if default is not None else 0.0
                elif f.kind == "bool":
                    w.value = bool(default)
                elif f.kind == "float_list":
                    init = ", ".join(map(str, default)) if isinstance(default, (list, tuple)) else (str(default) if default is not None else "")
                    w.value = init
                else:
                    w.value = str(default) if default is not None else ""
            except Exception:
                pass
        self.set_status("<em>Reset to defaults.</em>")


# ======================
# Configuration widget
# ======================
class ConfigurationWidget(BaseWidget):
    """
    Unified configuration widget with defaults:
      - ComponentSystem(1)
      - columns via DEFAULT_COLUMN_FACTORIES
      - models via MODEL_REGISTRY
      - ProcessBuilderForm as the inner form

    Adds:
      - "Components" IntText to rebuild columns on-the-fly
      - "Configure column…" popup to edit column.required_parameters
    """

    def __init__(
        self,
        *,
        title: Optional[str] = None,
        registry: Optional[dict[str, Callable[[Any], Any]]] = None,  # name -> (column) -> ModelSpec
        columns: Optional[Union[List[Any], Dict[str, Any]]] = None,
        on_built: Optional[Callable[[Any], None]] = None,
        spec_builder_cls: Optional[type] = None,  # defaults to ProcessBuilderForm
    ) -> None:
        # default wiring if pieces are missing
        use_defaults = (registry is None or columns is None or spec_builder_cls is None)
        if use_defaults:
            self._DEFAULT_COLUMN_FACTORIES = DEFAULT_COLUMN_FACTORIES
            self._can_rebuild_columns = True
            self._components_value = 1
            cs = ComponentSystem(self._components_value)
            columns = {name: factory(cs) for name, factory in self._DEFAULT_COLUMN_FACTORIES.items()}
            registry = MODEL_REGISTRY
            spec_builder_cls = ProcessBuilderForm
        else:
            self._DEFAULT_COLUMN_FACTORIES = None
            self._can_rebuild_columns = False
            self._components_value = None

        # manual-mode state
        self._elements: dict[str, Element] = {}
        self._btn_apply = W.Button(description="Apply", button_style="success")
        self._btn_reset = W.Button(description="Reset")

        # spec-driven state
        self._registry = registry
        self._columns = columns
        self._on_built = on_built
        self._SpecDriven = spec_builder_cls
        self.built: Any = None

        # listeners
        self._built_listeners: list[Callable[[Any], None]] = []

        # components field if we can rebuild
        self._components_field: Optional[W.IntText] = (
            W.IntText(description="Components:", value=self._components_value, min=1)
            if self._can_rebuild_columns else None
        )

        super().__init__(title=title or "Configuration")

    @property
    def process(self) -> Any:
        return self.built

    def add_built_listener(self, callback: Callable[[Any], None]) -> None:
        self._built_listeners.append(callback)

    # ---------- layout ----------
    def _build_body(self) -> W.Widget:
        self._manual_mode = not (self._registry and self._columns)

        if self._manual_mode:
            self._form_box = W.VBox([])
            self._actions = W.HBox([self._btn_apply, self._btn_reset])
            return W.VBox([self._form_box, self._actions])

        # keep a label->column list for popup title
        if isinstance(self._columns, dict):
            self._column_pairs: list[tuple[str, Any]] = list(self._columns.items())
        else:
            self._column_pairs = [(getattr(c, "name", c.__class__.__name__), c) for c in self._columns]

        self._model_picker = ObjectChoiceField(label="Model:", items=self._registry)
        self._column_picker = ChoiceField(label="Column:", options=self._column_pairs)

        # NEW: column config
        self._btn_config_col = W.Button(description="Configure column…", icon="wrench")
        self._col_popup = Popup(title="Column configuration")

        self._config_area = W.Box([])

        rows: list[W.Widget] = []
        if self._components_field is not None:
            rows.append(self._components_field)
        rows.append(W.HBox([self._model_picker.widget, self._column_picker.widget, self._btn_config_col]))
        rows.append(self._col_popup.widget)
        rows.append(self._config_area)
        return W.VBox(rows)

    def _wire_events(self) -> None:
        if getattr(self, "_manual_mode", False):
            self._btn_apply.on_click(self._on_apply)
            self._btn_reset.on_click(self._on_reset)
            return

        self._model_picker.widget.observe(self._on_spec_change, names="value")
        self._column_picker.widget.observe(self._on_spec_change, names="value")
        self._btn_config_col.on_click(self._on_open_column_config)

        # init selections
        try:
            mopts = list(self._model_picker.widget.options)
            if mopts:
                self._model_picker.set_value(mopts[0][1])
            copts = list(self._column_picker.widget.options)
            if copts:
                self._column_picker.set_value(copts[0][1])
        except Exception:
            pass

        # initial render
        model_fn = self._model_picker.get_value()
        column = self._column_picker.get_value()
        if model_fn and column:
            self._rebuild_spec_config(model_fn, column)

        if self._components_field is not None:
            self._components_field.observe(self._on_components_change, names="value")

    # ---------- manual-mode API ----------
    def add_field(self, name: str, element: Element) -> None:
        if not hasattr(self, "_form_box"):
            return
        self._elements[name] = element
        self._refresh_form()

    def set_values(self, values: Mapping[str, object]) -> None:
        if not hasattr(self, "_form_box"):
            return
        for k, v in values.items():
            el = self._elements.get(k)
            if el is not None:
                try:
                    el.set_value(v)
                except Exception:
                    pass
        self.set_status("Values updated.")

    def get_values(self) -> dict[str, object]:
        if not hasattr(self, "_form_box"):
            return {}
        out: dict[str, object] = {}
        for k, el in self._elements.items():
            try:
                out[k] = el.get_value()
            except Exception:
                out[k] = None
        return out

    def _on_apply(self, _btn: W.Button) -> None:  # noqa: ARG002
        if not hasattr(self, "_form_box"):
            return
        cfg = self.get_values()
        self.set_status(f"Applied: {cfg}")

    def _on_reset(self, _btn: W.Button) -> None:  # noqa: ARG002
        if not hasattr(self, "_form_box"):
            return
        for el in self._elements.values():
            try:
                el.set_value(el.get_value())
            except Exception:
                pass
        self.set_status("Reset done.")

    def _refresh_form(self) -> None:
        if hasattr(self, "_form_box"):
            self._form_box.children = [el.widget for el in self._elements.values()]

    # ---------- spec-driven internals ----------
    def _on_spec_change(self, _change) -> None:
        model_fn = self._model_picker.get_value()
        column = self._column_picker.get_value()
        if model_fn and column:
            self._rebuild_spec_config(model_fn, column)

    def _on_components_change(self, change) -> None:
        if not self._can_rebuild_columns or change["name"] != "value":
            return
        try:
            n = int(change["new"])
            if n < 1:
                return
        except Exception:
            return

        cs = ComponentSystem(n)
        new_columns = {name: factory(cs) for name, factory in self._DEFAULT_COLUMN_FACTORIES.items()}  # type: ignore[index]
        self._columns = new_columns
        pairs = [(label, col) for label, col in new_columns.items()]
        self._column_pairs = pairs
        self._column_picker.widget.options = pairs  # type: ignore[attr-defined]
        if pairs:
            self._column_picker.set_value(pairs[0][1])
        model_fn = self._model_picker.get_value()
        column = self._column_picker.get_value()
        if model_fn and column:
            self._rebuild_spec_config(model_fn, column)
        self.set_status(f"<em>Rebuilt columns for {n} component(s).</em>")

    def _notify_built(self) -> None:
        if self.built is None:
            return
        for cb in list(self._built_listeners):
            try:
                cb(self.built)
            except Exception:
                pass

    def _rebuild_spec_config(self, model_fn: Callable[[Any], Any], column: Any) -> None:
        SpecDriven = self._SpecDriven
        if SpecDriven is None:
            raise RuntimeError("ProcessBuilderForm class not provided.")
        spec = model_fn(column)
        form = SpecDriven(spec)

        # Copy the built process out after the inner Apply (button already bound in form)
        def _after_apply(_b):
            if getattr(form, "built", None) is not None:
                self.built = form.built
                if self._on_built is not None:
                    self._on_built(form.built)
                self._notify_built()

        form._btn_apply.on_click(_after_apply)  # type: ignore[attr-defined]
        self._config_area.children = [form.root]
        self.set_status("<em>Select model & column, configure, then click Apply.</em>")

    def _on_open_column_config(self, _btn) -> None:
        """Build and show a popup form for the currently selected column."""
        try:
            column = self._column_picker.get_value()
            spec = column_spec_from_required(column)
            form = ProcessBuilderForm(spec)

            def _after_apply(_b):
                name = getattr(column, "name", column.__class__.__name__)
                self.set_status(f"<em>Updated column parameters for: {name}</em>")

            form._btn_apply.on_click(_after_apply)  # type: ignore[attr-defined]
            self._col_popup.widget.children = [form.root]
            self._col_popup.open()
        except Exception as e:
            self._col_popup.widget.children = [W.HTML(f"<span style='color:#b00'>Error: {e}</span>")]
            self._col_popup.open()


# ======================
# Solution widget
# ======================

def _try_plot_result(res: Any, out_widget: W.Output) -> None:
    import numpy as np
    import pprint
    try:
        import matplotlib.pyplot as plt  # noqa: F401
    except Exception:
        plt = None

    with out_widget:
        # pandas-like
        if hasattr(res, "to_pandas") and callable(res.to_pandas):
            try:
                df = res.to_pandas()  # type: ignore[attr-defined]
                from IPython.display import display
                print("Result (first rows):")
                display(df.head())
                if plt is not None:
                    cols: List[str] = list(df.columns)
                    tcol = "time" if "time" in cols else ("t" if "t" in cols else None)
                    ycols = [c for c in cols if c not in ("time", "t")]
                    if tcol and ycols:
                        plt.figure()
                        plt.plot(df[tcol], df[ycols[0]])
                        plt.xlabel(tcol)
                        plt.ylabel(ycols[0])
                        plt.title("Simulation (first series)")
                        plt.show()
                return
            except Exception as e:
                print(f"(Could not render DataFrame view: {e})")

        # simple dict plot
        if isinstance(res, dict):
            t = res.get("time", res.get("t"))
            if t is not None and plt is not None:
                for k, v in res.items():
                    if k in ("time", "t"):
                        continue
                    try:
                        tt = np.asarray(t)
                        yy = np.asarray(v)
                        if tt.ndim == 1 and yy.ndim >= 1 and yy.shape[0] == tt.shape[0]:
                            plt.figure()
                            plt.plot(tt, yy)
                            plt.xlabel("time")
                            plt.ylabel(k)
                            plt.title("Simulation")
                            plt.show()
                            return
                    except Exception:
                        pass
            print("Result dictionary:")
            pprint.pprint(res)
            return

        # fallback print
        print("Simulation result:")
        pprint.pprint(res)


class SolutionWidget(BaseWidget):
    """
    Takes a Process and runs it (using CADETProcess.simulator by default).
    Can also bind to a ConfigurationWidget to receive the built process on Apply.
    """

    def __init__(
        self,
        *,
        title: Optional[str] = None,
        process: Any = None,
        config: ConfigurationWidget | None = None,
        runner: Callable[[Any], Any] | None = None,
        runner_kwargs: Dict[str, Any] | None = None,
    ) -> None:
        self._process: Any = None
        self._btn_run = W.Button(description="Run simulation", icon="play")
        self._btn_clear = W.Button(description="Clear", icon="trash")
        self._proc_label = W.HTML("<em>No process set.</em>")
        self._out = W.Output()
        self._show_tb = W.Checkbox(description="Show traceback", value=True)

        self._runner = runner or _default_runner
        self._runner_kwargs = runner_kwargs or {}

        super().__init__(title=title or "Solution")

        if process is not None:
            self.set_process(process)
        if config is not None:
            self.bind_to_config(config)

    def set_process(self, process: Any) -> None:
        self._process = process
        name = getattr(process, "name", process.__class__.__name__)
        self._proc_label.value = f"<strong>Process:</strong> {name}"
        self.set_status("<em>Ready to run.</em>")

    def bind_to_config(self, config_widget: ConfigurationWidget) -> None:
        config_widget.add_built_listener(self.set_process)
        try:
            if config_widget.process is not None:
                self.set_process(config_widget.process)
        except Exception:
            pass

    def _build_body(self) -> W.Widget:
        controls = W.HBox([self._btn_run, self._btn_clear, self._show_tb])
        header = W.HBox([self._proc_label, controls])
        return W.VBox([header, self._out])

    def _wire_events(self) -> None:
        self._btn_run.on_click(self._on_run)
        self._btn_clear.on_click(self._on_clear)

    def _on_run(self, _btn) -> None:
        self._out.clear_output()
        if self._process is None:
            self.set_status("<span style='color:#b00'>No process to run. Build one first.</span>")
            return

        capture = bool(self._show_tb.value)
        buf_out = io.StringIO() if capture else None
        buf_err = io.StringIO() if capture else None

        try:
            if capture:
                with redirect_stdout(buf_out), redirect_stderr(buf_err):
                    res = self._runner(self._process, **self._runner_kwargs)
            else:
                res = self._runner(self._process, **self._runner_kwargs)

            with self._out:
                if capture:
                    out_txt = buf_out.getvalue()
                    err_txt = buf_err.getvalue()
                    if out_txt.strip():
                        print("=== stdout ===")
                        print(out_txt, end="")
                    if err_txt.strip():
                        print("=== stderr ===")
                        print(err_txt, end="")
                print("Simulation finished.")

            _try_plot_result(res, self._out)
            self.set_status("<em>Simulation complete.</em>")

        except Exception as e:
            with self._out:
                if capture:
                    tb = traceback.TracebackException.from_exception(e, capture_locals=True)
                    text = "".join(tb.format(chain=True))
                    if buf_out:
                        out_txt = buf_out.getvalue()
                        if out_txt.strip():
                            print("=== stdout (captured) ===")
                            print(out_txt, end="")
                    if buf_err:
                        err_txt = buf_err.getvalue()
                        if err_txt.strip():
                            print("=== stderr (captured) ===")
                            print(err_txt, end="")
                    print("=== full traceback (with chained causes) ===")
                    print(text, end="")
                else:
                    print(f"{e.__class__.__name__}: {e}")
            self.set_status(f"<span style='color:#b00'>Simulation error: {e}</span>")

    def _on_clear(self, _btn) -> None:
        self._out.clear_output()
        self.set_status("<em>Cleared.</em>")
