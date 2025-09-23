# =========================================
# File: cadetgui/widgets/solution.py
# =========================================
from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Mapping, Sequence, Tuple
from contextlib import redirect_stderr, redirect_stdout

import ipywidgets as W

from .base import BaseWidget
from ..simulation import run_process as _default_runner

try:
    from collections.abc import Mapping as _MappingABC
except Exception:  # pragma: no cover
    _MappingABC = dict  # type: ignore

__all__ = ["SolutionWidget", "solution_to_fields_lenmatch"]

# ---- Optional import for nicer isinstance checks (kept soft)
try:  # pragma: no cover - optional convenience
    from CADETProcess.fields import Field as _FieldType  # type: ignore
except Exception:  # pragma: no cover - fallback to duck typing
    _FieldType = Any  # type: ignore


# ----------------------------
# Generic helpers
# ----------------------------
def _is_field(obj: Any) -> bool:
    """Duck-type check for CADETProcess Field-like objects."""
    if _FieldType is not Any:
        try:
            return isinstance(obj, _FieldType)
        except Exception:
            pass
    req = ["plot", "sel", "interp", "differentiate", "integrate", "coordinates"]
    return all(hasattr(obj, name) for name in req)


def _try_plot_result_generic(result: Any, out: W.Output) -> None:
    """Best-effort, generic plotting hook (safer checks)."""
    try:
        import matplotlib.pyplot as plt  # type: ignore
        with out:
            plot_attr = getattr(result, "plot", None)
            if callable(plot_attr):
                plot_attr()
                return
            if isinstance(result, dict) and "t" in result and "y" in result:
                t, y = result["t"], result["y"]
                plt.figure()
                plt.plot(t, y)
                plt.xlabel("t")
                plt.ylabel("y")
                plt.show()
            else:
                print(repr(result))
    except Exception:
        pass


def _get_attr_or_key(obj: Any, *names: str, default: Any = None) -> Any:
    """Return first found attribute or mapping key from names, else default."""
    for n in names:
        try:
            if hasattr(obj, n):
                return getattr(obj, n)
            if isinstance(obj, _MappingABC) and n in obj:  # type: ignore[arg-type]
                return obj[n]
        except Exception:
            pass
    return default


def _is_monotonic_increasing(arr: Any) -> bool:
    try:
        import numpy as _np
        a = _np.asarray(arr)
        if a.ndim != 1 or a.size < 2:
            return False
        return _np.all(_np.diff(a) >= 0)
    except Exception:
        return False


# ----------------------------
# Field builders / coercion
# ----------------------------
def _best_time_array(obj: Any) -> Any:
    """Try to find a plausible time array on an object."""
    cand = _get_attr_or_key(obj, "time", "t")
    if cand is not None:
        return cand
    try:
        import numpy as _np
        best = None
        for name in dir(obj):
            if name.startswith("_"):
                continue
            try:
                v = getattr(obj, name)
            except Exception:
                continue
            try:
                a = _np.asarray(v)
            except Exception:
                continue
            if a.ndim == 1 and a.size >= 2 and _is_monotonic_increasing(a):
                lname = name.lower()
                score = 1
                if "time" in lname or lname == "t":
                    score = 0
                if best is None or score < best[0]:
                    best = (score, v)
        return best[1] if best else None
    except Exception:
        return None


def _pick_data_array(obj: Any, t_len: int) -> Any:
    """Pick a plausible data array on an object given a time length."""
    data = _get_attr_or_key(obj, "c", "y", "data", "values", "signal")
    if data is not None:
        return data
    try:
        import numpy as _np
        best = None
        for name in dir(obj):
            if name.startswith("_"):
                continue
            try:
                v = getattr(obj, name)
            except Exception:
                continue
            try:
                a = _np.asarray(v)
            except Exception:
                continue
            if a.ndim >= 1 and a.shape[0] == t_len:
                score = -a.ndim
                if best is None or score < best[0]:
                    best = (score, v)
        return best[1] if best else None
    except Exception:
        return None


def _build_field_from_solution(solution: Any, *, name: Optional[str] = None) -> Any:
    """Best-effort: turn a SolutionIO.solution-like object into a Field."""
    try:
        from CADETProcess.fields import Field as FieldCls  # type: ignore
    except Exception:
        FieldCls = None  # type: ignore

    if FieldCls is None:
        return solution  # Can't build Field without Field class

    t = _get_attr_or_key(solution, "time", "t")
    axial = _get_attr_or_key(solution, "axial", "z", "x")
    radial = _get_attr_or_key(solution, "radial", "r")

    data = _get_attr_or_key(solution, "c", "y", "data", "values")
    comps = _get_attr_or_key(solution, "components", "comp_names", "species")
    unit = _get_attr_or_key(solution, "unit", "units")

    if data is None or t is None:
        return solution

    coords: Dict[str, Any] = {"time": (t, "s")}
    if axial is not None:
        coords["axial"] = (axial, "m")
    if radial is not None:
        coords["radial"] = (radial, "m")

    try:
        fld = FieldCls(
            coordinates=coords,
            data=data,
            components=list(comps) if comps is not None else None,
            name=name,
            unit=unit,
        )
        return fld
    except Exception:
        return solution


def _coerce_to_fieldish(result: Any) -> Any:
    """Try to coerce common simulation result containers into Field or dict-of-Field."""
    if _is_field(result):
        return result

    if isinstance(result, Mapping) and result and all(_is_field(v) for v in result.values()):
        return result

    # `.fields` mapping
    try:
        fields_map = getattr(result, "fields")
        if isinstance(fields_map, Mapping) and fields_map and all(_is_field(v) for v in fields_map.values()):
            return fields_map
    except Exception:
        pass

    # `to_fields` / `as_fields` / `to_field`
    for meth in ("to_fields", "as_fields", "to_field"):
        fn = getattr(result, meth, None)
        if callable(fn):
            try:
                val = fn()
                if _is_field(val):
                    return val
                if isinstance(val, Mapping) and val and all(_is_field(v) for v in val.values()):
                    return val
            except Exception:
                pass

    # `.solution` mapping with nested SolutionIO → try to build Field
    solmap = _get_attr_or_key(result, "solution")
    if isinstance(solmap, Mapping) and solmap:
        converted: Dict[str, Any] = {}
        for unit_name, io_map in solmap.items():
            if isinstance(io_map, Mapping):
                for port_name, io in io_map.items():
                    sol = _get_attr_or_key(io, "solution")
                    key = f"{unit_name}:{port_name}"
                    fld = _build_field_from_solution(sol, name=key)
                    if _is_field(fld):
                        converted[key] = fld
                    elif sol is None:
                        fld2 = _build_field_from_solution(io, name=key)
                        if _is_field(fld2):
                            converted[key] = fld2
        if converted:
            return converted

    # Generic mapping: keep Field entries found recursively
    if isinstance(result, Mapping) and result:
        sub: Dict[str, Any] = {}
        for k, v in result.items():
            cv = _coerce_to_fieldish(v)
            if _is_field(cv):
                sub[k] = cv
        if sub:
            return sub

    return result


# ----------------------------
# Coordinate normalizer
# ----------------------------
def _coords_with_units(field: Any) -> Dict[str, Tuple["np.ndarray", Optional[str]]]:
    """
    Normalize coordinates to: {dim: (grid_ndarray, unit_or_None)}.

    Prefers xarray attrs when available (field.data[dim].attrs["units"]).
    Falls back to field.coordinates and accepts either bare arrays or (values, unit) tuples.
    """
    import numpy as np

    # Preferred: via xarray DataArray
    try:
        da = getattr(field, "data", None)
        if da is not None:
            out: Dict[str, Tuple[np.ndarray, Optional[str]]] = {}
            for dim in da.dims:
                vals = np.asarray(da.coords[dim].values)
                unit = da.coords[dim].attrs.get("units")
                out[dim] = (vals, unit)
            return out
    except Exception:
        pass

    # Fallback: whatever field.coordinates exposes
    out: Dict[str, Tuple[np.ndarray, Optional[str]]] = {}
    raw = getattr(field, "coordinates", {}) or {}
    if isinstance(raw, dict):
        for dim, val in raw.items():
            unit = None
            arr = val
            # Support legacy tuples: (values, unit)
            if isinstance(val, tuple) and len(val) == 2:
                arr, unit = val
            try:
                arr = np.asarray(arr)
            except Exception:
                pass
            out[dim] = (arr, unit)
    return out


# ----------------------------
# Result transform that really uses solution arrays + real time
# ----------------------------
def solution_to_fields_lenmatch(res):
    """
    Flatten res.solution (unit -> {port -> SolutionIO}) into
    { "unit:port": Field } by:
      - getting data from io.solution (numpy array)
      - inferring T from the data
      - locating a unit/global 1D 'time' vector (handles {'values': ...} holders)
      - falling back to arange(T) only if necessary
    """
    from CADETProcess.fields import Field  # type: ignore
    import numpy as np

    solmap = getattr(res, "solution", None)
    if not isinstance(solmap, Mapping):
        return res

    def _safe_arr(x):
        try:
            return np.asarray(x)
        except Exception:
            try:
                return np.asarray(list(x))
            except Exception:
                return None

    def _as_vector(x):
        """Extract a vector from common wrappers (dict with 'values', obj.values)."""
        if x is None:
            return None
        # mapping with 'values'
        if isinstance(x, Mapping) and "values" in x:
            return _safe_arr(x["values"])
        # objects with non-callable .values
        vals = getattr(x, "values", None)
        if vals is not None and not callable(vals):
            return _safe_arr(vals)
        # plain array-like
        return _safe_arr(x)

    def _scan_time(scope: Mapping, T: int):
        """Find a 1D vector of length T in mapping scope, prefer monotonic & 'time' names."""
        best = None
        # 1) direct names that may be wrappers
        for key in ("time", "t"):
            cand = None
            if isinstance(scope, Mapping):
                if key in scope:
                    cand = _as_vector(scope[key])
            if cand is not None and cand.ndim == 1 and cand.size == T:
                return cand
        # 2) nested holders like scope['time'] == {'values': ...}
        for k, v in scope.items():
            if isinstance(v, Mapping) and "values" in v:
                cand = _safe_arr(v["values"])
                if cand is not None and cand.ndim == 1 and cand.size == T:
                    return cand
        # 3) generic scan of 1D arrays
        for k, v in scope.items():
            cand = _as_vector(v)
            if cand is None or cand.ndim != 1 or cand.size != T:
                continue
            return cand
        return None

    out: Dict[str, Any] = {}

    for unit, ports in solmap.items():
        if not isinstance(ports, Mapping):
            continue

        # Deduce T from any port's data
        T = None
        for _p, io in ports.items():
            data0 = _as_vector(getattr(io, "solution", None))
            if data0 is None:
                continue
            if data0.ndim >= 1:
                T = int(data0.shape[0])
                break
        if T is None:
            continue

        # Find a unit-level time first; else global; else synthetic
        t = _scan_time(ports, T)
        if t is None and isinstance(solmap, Mapping):
            gt = _scan_time(solmap, T)
            if gt is not None:
                t = gt
        if t is None:
            t = np.arange(T)

        for port, io in ports.items():
            data = _as_vector(getattr(io, "solution", None))
            if data is None or data.ndim < 1:
                continue

            # Align time dimension
            if data.shape[0] != T and data.shape[-1] == T:
                data = np.swapaxes(data, 0, -1)
            if data.shape[0] != T:
                continue

            coords = {"time": (t, "s")}
            comp_names = None
            if data.ndim >= 2 and 1 < data.shape[-1] <= 64:
                comp_names = [f"C{i}" for i in range(data.shape[-1])]

            try:
                out[f"{unit}:{port}"] = Field(
                    coordinates=coords,
                    data=data,
                    components=comp_names,
                    name=f"{unit}:{port}",
                )
            except Exception:
                pass

    return out if out else solmap


# ----------------------------
# Widget
# ----------------------------
class SolutionWidget(BaseWidget):
    """Runner/visualizer for CADET-Process processes with Field-aware tooling."""

    def __init__(
        self,
        *,
        title: Optional[str] = None,
        process: Any = None,
        config: Optional["ConfigurationWidget"] = None,
        runner: Optional[Callable[[Any], Any]] = None,
        runner_kwargs: Optional[Dict[str, Any]] = None,
        result_transform: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        self._process: Any | None = None
        self._btn_run = W.Button(description="Run simulation", icon="play")
        self._btn_clear = W.Button(description="Clear", icon="trash")
        self._proc_label = W.HTML("<em>No process set.</em>")
        self._out = W.Output()
        self._show_tb = W.Checkbox(description="Show traceback", value=True)

        self._runner = runner or _default_runner
        self._runner_kwargs = runner_kwargs or {}
        self._result_transform = result_transform

        # Field-aware UI (created lazily when needed)
        self._field_container = W.VBox(layout=W.Layout(display="none"))
        self._field_controls: Dict[str, W.Widget] = {}
        self._current_result: Any = None  # last result object (possibly transformed/coerced)

        # Result inspector UI (always visible after a run)
        self._result_info = W.HTML(value="")
        self._result_key_dd = W.Dropdown(description="Result key", options=(), layout=W.Layout(width="auto"))
        self._result_bar = W.HBox([self._result_info, self._result_key_dd], layout=W.Layout(display="none", gap="12px"))
        self._result_key_dd.observe(lambda _ch: self._on_result_key_changed(), names="value")

        # Track the last figure we drew so we can close it
        self._last_fig = None  # type: ignore

        super().__init__(title=title or "Solution")

        if process is not None:
            self.set_process(process)
        if config is not None:
            self.bind_to_config(config)

    # ----- public API -----
    def set_process(self, process: Any) -> None:
        self._process = process
        self._proc_label.value = (
            f"<strong>Process:</strong> {getattr(process, 'name', process.__class__.__name__)}"
        )
        self.set_status("<em>Ready to run.</em>")

    def bind_to_config(self, config_widget: "ConfigurationWidget") -> None:
        # Late import to avoid circular typing issues
        from .config import ConfigurationWidget  # noqa: WPS433

        if not isinstance(config_widget, ConfigurationWidget):
            raise TypeError("config_widget must be a ConfigurationWidget")

        config_widget.add_listener(self.set_process)
        if config_widget.process is not None:
            self.set_process(config_widget.process)

    # ----- UI -----
    def _build_body(self) -> W.Widget:
        controls = W.HBox([self._btn_run, self._btn_clear, self._show_tb])
        return W.VBox(
            [
                W.HBox([self._proc_label, controls]),
                self._result_bar,
                self._field_container,
                self._out,
            ]
        )

    def _wire_events(self) -> None:
        self._btn_run.on_click(self._on_run)
        self._btn_clear.on_click(self._on_clear)

    # ----- events -----
    def _on_run(self, _btn: W.Button) -> None:
        self._out.clear_output()
        self._hide_field_ui()
        self._hide_result_bar()
        if self._process is None:
            self.set_error("No process to run. Build one first.")
            return

        import io
        import traceback as _tb

        capture = bool(self._show_tb.value)
        buf_out, buf_err = (io.StringIO(), io.StringIO()) if capture else (None, None)

        try:
            if capture:
                with redirect_stdout(buf_out), redirect_stderr(buf_err):
                    raw = self._runner(self._process, **self._runner_kwargs)
            else:
                raw = self._runner(self._process, **self._runner_kwargs)

            # Optional transform, then coercion to Field-ish structures
            result = self._result_transform(raw) if callable(self._result_transform) else raw
            result = _coerce_to_fieldish(result)
            self._current_result = result

            # Show result meta / selector if needed
            self._show_result_bar(result)

            with self._out:
                if capture:
                    if buf_out and buf_out.getvalue().strip():
                        print("=== stdout ===")
                        print(buf_out.getvalue(), end="")
                    if buf_err and buf_err.getvalue().strip():
                        print("=== stderr ===")
                        print(buf_err.getvalue(), end="")
                print("Simulation finished.")

            # If it's Field-like, expose Field controls; if mapping try to plot one entry; else fallback
            if self._render_field_ui_if_applicable(result):
                self.set_status("<em>Field detected — use controls to slice/plot.</em>")
                self._plot_field_from_controls()
            elif isinstance(result, Mapping):
                self._attempt_plot_from_mapping(result)
            else:
                with self._out:
                    print(repr(result))
                _try_plot_result_generic(result, self._out)
                self.set_status("<em>Simulation complete.</em>")

        except Exception as exc:  # noqa: BLE001
            with self._out:
                if capture:
                    tb = _tb.TracebackException.from_exception(exc, capture_locals=True)
                    if buf_out and buf_out.getvalue().strip():
                        print("=== stdout (captured) ===")
                        print(buf_out.getvalue(), end="")
                    if buf_err and buf_err.getvalue().strip():
                        print("=== stderr (captured) ===")
                        print(buf_err.getvalue(), end="")
                    print("=== full traceback (with chained causes) ===")
                    print("".join(tb.format(chain=True)), end="")
                else:
                    print(f"{exc.__class__.__name__}: {exc}")
            self.set_error(f"Simulation error: {exc}")

    def _on_clear(self, _btn: W.Button) -> None:
        self._out.clear_output()
        self._hide_field_ui()
        self._hide_result_bar()
        self.set_status("<em>Cleared.</em>")

    # ----- Result bar -----
    def _hide_result_bar(self) -> None:
        self._result_bar.layout.display = "none"
        self._result_info.value = ""
        self._result_key_dd.options = ()

    def _show_result_bar(self, result: Any) -> None:
        typ = type(result).__name__
        if isinstance(result, Mapping):
            keys = list(result.keys())
            self._result_info.value = f"<b>Result:</b> Mapping[{len(keys)}], type={typ}"
            self._result_key_dd.options = [(str(k), k) for k in keys]
            self._result_key_dd.value = keys[0] if keys else None
            self._result_bar.layout.display = "flex"
        else:
            self._result_info.value = f"<b>Result:</b> {typ}"
            self._result_key_dd.options = ()
            self._result_bar.layout.display = "flex"

    def _on_result_key_changed(self) -> None:
        if not isinstance(self._current_result, Mapping) or not self._current_result:
            return
        key = self._result_key_dd.value
        val = self._current_result.get(key)
        self._out.clear_output()
        self._hide_field_ui()
        if self._render_field_ui_if_applicable(val):
            self._plot_field_from_controls()
            self.set_status(f"<em>Viewing: {key}</em>")
        else:
            with self._out:
                print(repr(val))
            _try_plot_result_generic(val, self._out)
            self.set_status(f"<em>Viewing: {key}</em>")

    def _attempt_plot_from_mapping(self, mapping: Mapping[str, Any]) -> None:
        # Prefer the first Field in the mapping, if any
        for k, v in mapping.items():
            if _is_field(v):
                self._result_key_dd.value = k
                self._on_result_key_changed()  # route through the normal path
                return

        # Fallback: generic repr/plot of the first entry
        first_key = next(iter(mapping.keys())) if mapping else None
        val = mapping.get(first_key) if first_key is not None else None
        with self._out:
            print(repr(mapping))
            if first_key is not None:
                print("--- First entry ---")
                print(repr(val))
        _try_plot_result_generic(val, self._out)
        self.set_status("<em>No Field found in mapping.</em>")

    # ----- Field-aware UI -----
    def _hide_field_ui(self) -> None:
        self._field_container.layout.display = "none"
        self._field_container.children = ()
        self._field_controls.clear()

    def _render_field_ui_if_applicable(self, result: Any) -> bool:
        # Determine the single Field to render controls for
        if _is_field(result):
            field = result
        elif isinstance(result, Mapping) and result and all(_is_field(v) for v in result.values()):
            # Use currently selected key from the result bar
            key = self._result_key_dd.value
            if key is None or key not in result:
                key = next(iter(result.keys()))
            field = result[key]
        else:
            return False

        rows: list[W.Widget] = []

        # Components UI (if any)
        components: Sequence[str] | None = getattr(field, "components", None)
        if components is not None and len(components) > 0:
            comp_sel = W.SelectMultiple(
                description="Components",
                options=list(components),
                value=tuple(components),
                layout=W.Layout(width="420px", height="120px"),
            )
            self._field_controls["components"] = comp_sel
            comp_sel.observe(lambda _ch: self._plot_field_from_controls(), names="value")
            rows.append(comp_sel)

        # Slicing controls
        coords = _coords_with_units(field)
        slicer_boxes: list[W.Widget] = []
        for name, (grid, unit) in coords.items():
            ulabel = f"[{unit}]" if unit else ""
            cb_fix = W.Checkbox(description=f"Fix {name} {ulabel}".strip(), value=False)
            val = W.FloatText(
                description=f"{name}=",
                value=float(grid[0]) if hasattr(grid, "__len__") and len(grid) > 0 else 0.0,
                layout=W.Layout(width="220px"),
            )
            method = W.Dropdown(
                description="method",
                options=["exact", "nearest"],
                value="exact",
                layout=W.Layout(width="150px"),
            )
            hb = W.HBox([cb_fix, val, method])
            self._field_controls[f"fix_{name}"] = cb_fix
            self._field_controls[f"val_{name}"] = val
            self._field_controls[f"method_{name}"] = method
            for w in (cb_fix, val, method):
                w.observe(lambda _ch: self._plot_field_from_controls(), names="value")
            slicer_boxes.append(hb)
        if slicer_boxes:
            rows.append(W.VBox([W.HTML("<b>Slicing</b>"), *slicer_boxes]))

        coord_names = list(coords.keys())

        # Interpolation controls
        interp_enable = W.Checkbox(description="Interpolate", value=False)
        interp_axis = W.Dropdown(
            description="along",
            options=coord_names,
            value=coord_names[0] if coord_names else None,
        )
        interp_points = W.IntText(description="points", value=100)
        hb_interp = W.HBox([interp_enable, interp_axis, interp_points])
        self._field_controls["interp_enable"] = interp_enable
        self._field_controls["interp_axis"] = interp_axis
        self._field_controls["interp_points"] = interp_points
        for w in (interp_enable, interp_axis, interp_points):
            w.observe(lambda _ch: self._plot_field_from_controls(), names="value")
        rows.append(W.VBox([W.HTML("<b>Interpolation</b>"), hb_interp]))

        # Calculus controls
        calc_mode = W.Dropdown(
            description="Operation",
            options=["None", "Differentiate", "Integrate"],
            value="None",
        )
        calc_axis = W.Dropdown(
            description="w.r.t.",
            options=coord_names,
            value=coord_names[0] if coord_names else None,
        )
        hb_calc = W.HBox([calc_mode, calc_axis])
        self._field_controls["calc_mode"] = calc_mode
        self._field_controls["calc_axis"] = calc_axis
        for w in (calc_mode, calc_axis):
            w.observe(lambda _ch: self._plot_field_from_controls(), names="value")
        rows.append(W.VBox([W.HTML("<b>Analysis</b>"), hb_calc]))

        # Plot button
        btn_plot = W.Button(description="Plot", icon="line-chart")
        btn_plot.on_click(lambda _b: self._plot_field_from_controls())
        rows.append(btn_plot)

        self._field_container.children = tuple(rows)
        self._field_container.layout.display = "block"
        return True

    def _gather_slice_kwargs(self) -> Dict[str, Tuple[float, str]]:
        kwargs: Dict[str, Tuple[float, str]] = {}
        for key, widget in self._field_controls.items():
            if key.startswith("fix_") and isinstance(widget, W.Checkbox) and widget.value:
                coord = key[len("fix_") :]
                valw = self._field_controls.get(f"val_{coord}")
                methw = self._field_controls.get(f"method_{coord}")
                if isinstance(valw, W.FloatText) and isinstance(methw, W.Dropdown):
                    kwargs[coord] = (float(valw.value), str(methw.value))
        return kwargs

    def _get_active_field(self) -> Any:
        # If we have a mapping, prefer the currently selected Result key
        if isinstance(self._current_result, Mapping):
            key = self._result_key_dd.value
            if key is not None and key in self._current_result:
                return self._current_result[key]
        # Otherwise, the result itself is a Field (or something else)
        return self._current_result

    def _apply_interpolation(self, fld: Any) -> Any:
        enable = self._field_controls.get("interp_enable")
        axis = self._field_controls.get("interp_axis")
        points = self._field_controls.get("interp_points")
        if isinstance(enable, W.Checkbox) and enable.value and isinstance(axis, W.Dropdown) and isinstance(points, W.IntText):
            coords = _coords_with_units(fld)
            if axis.value in coords:
                grid, _unit = coords[axis.value]
                if len(grid) >= 2 and points.value > 1:
                    import numpy as np  # local import
                    new_grid = np.linspace(float(grid[0]), float(grid[-1]), int(points.value))
                    try:
                        return fld.interp(**{axis.value: new_grid})
                    except Exception:
                        return fld
        return fld

    def _apply_calculus(self, fld: Any) -> Any:
        mode = self._field_controls.get("calc_mode")
        axis = self._field_controls.get("calc_axis")
        if isinstance(mode, W.Dropdown) and isinstance(axis, W.Dropdown):
            try:
                if mode.value == "Differentiate" and axis.value:
                    return fld.differentiate(axis.value)
                if mode.value == "Integrate" and axis.value:
                    return fld.integrate(axis.value)
            except Exception:
                return fld
        return fld

    def _plot_field_from_controls(self) -> None:
        import matplotlib.pyplot as plt  # local import

        # Clear UI output (avoid accumulating figures)
        self._out.clear_output(wait=True)

        # Close previous figure if we created one
        if getattr(self, "_last_fig", None) is not None:
            try:
                plt.close(self._last_fig)
            except Exception:
                pass
            self._last_fig = None

        fld = self._get_active_field()
        if not _is_field(fld):
            with self._out:
                print("No Field to plot.")
            return

        fld2 = self._apply_interpolation(fld)
        fld3 = self._apply_calculus(fld2)

        # Slicing
        slice_kwargs = self._gather_slice_kwargs()
        if slice_kwargs:
            try:
                for coord, (value, method) in slice_kwargs.items():
                    if method == "nearest":
                        fld3 = fld3.sel(**{coord: value}, method="nearest")
                    else:
                        fld3 = fld3.sel(**{coord: value})
            except Exception:
                pass

        # Component selection (optional)
        comp_sel = self._field_controls.get("components")
        if isinstance(comp_sel, W.SelectMultiple) and comp_sel.value:
            try:
                if len(comp_sel.value) == 1:
                    fld3 = fld3[comp_sel.value[0]]
            except Exception:
                pass

        # Try plotting; capture the created figure so we can close it next time
        try:
            with self._out:
                ax_or_axes = fld3.plot({})
                # Try to detect the figure object
                try:
                    fig = None
                    if hasattr(ax_or_axes, "get_figure"):
                        fig = ax_or_axes.get_figure()
                    else:
                        if hasattr(ax_or_axes, "ravel"):
                            flat = ax_or_axes.ravel()
                            if flat and hasattr(flat[0], "get_figure"):
                                fig = flat[0].get_figure()
                    if fig is None:
                        fig = plt.gcf()
                    self._last_fig = fig
                except Exception:
                    self._last_fig = None
        except Exception:
            try:
                with self._out:
                    # Fallback: fix all dims at first entry
                    coords = _coords_with_units(fld3)
                    fixed = {
                        dim: grid[0]
                        for dim, (grid, _unit) in coords.items()
                        if hasattr(grid, "__len__") and len(grid) > 0
                    }
                    ax_or_axes = fld3.plot(fixed)
                    try:
                        fig = None
                        if hasattr(ax_or_axes, "get_figure"):
                            fig = ax_or_axes.get_figure()
                        else:
                            if hasattr(ax_or_axes, "ravel"):
                                flat = ax_or_axes.ravel()
                                if flat and hasattr(flat[0], "get_figure"):
                                    fig = flat[0].get_figure()
                        if fig is None:
                            fig = plt.gcf()
                        self._last_fig = fig
                    except Exception:
                        self._last_fig = None
            except Exception:
                _try_plot_result_generic(fld3, self._out)
                self._last_fig = None

        self.set_status("<em>Plotted.</em>")
