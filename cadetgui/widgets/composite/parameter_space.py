from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import ipywidgets as W

from ...parameter_estimation import FittableParameter
from ..elements import ChoiceField

__all__ = ["ParameterSpaceEditor"]

_Key = Tuple[str, str, Optional[int]]


class ParameterSpaceEditor:
    """The "Configure parameter space" section: an "Add parameter" picker + rows.

    Each row holds one fittable parameter's start/lower/upper-bound fields.

    Row order and each row's own start/lb/ub survive a row being removed and
    re-added, and survive the owner replacing `.params` wholesale (e.g. after
    a configuration edit) as long as a parameter's identity key still exists
    -- see `set_params`.
    """

    _NAME_WIDTH = "300px"
    _FIELD_WIDTH = "110px"
    _REMOVE_WIDTH = "36px"

    def __init__(self) -> None:
        self.params: List[FittableParameter] = []
        self._added_keys: List[_Key] = []
        self._param_state: Dict[_Key, Dict[str, float]] = {}
        self._lb_fields: List[W.FloatText] = []
        self._ub_fields: List[W.FloatText] = []
        self._start_fields: List[W.FloatText] = []
        self._remove_buttons: List[W.Button] = []

        # "Add parameter" picker + button.
        self._param_add_picker = ChoiceField(label="Add parameter:", options=[])
        self._btn_add_param = W.Button(description="Add", icon="plus")
        self._btn_add_param.on_click(self._on_add_param)

        # Column header row above the added-parameter rows. Fixed column
        # widths -- every row (and this header) uses the exact same ones, so
        # start/lb/ub actually line up regardless of how long a given
        # parameter's own label is.
        self._param_header = W.HBox(
            [
                W.HTML("<b>Parameter</b>", layout=W.Layout(width=self._NAME_WIDTH)),
                W.HTML("<b>Start</b>", layout=W.Layout(width=self._FIELD_WIDTH)),
                W.HTML("<b>Lower bound</b>", layout=W.Layout(width=self._FIELD_WIDTH)),
                W.HTML("<b>Upper bound</b>", layout=W.Layout(width=self._FIELD_WIDTH)),
                W.HTML("", layout=W.Layout(width=self._REMOVE_WIDTH)),
            ]
        )
        # Filled in by _refresh_added_rows() with one row per added parameter.
        self._param_box = W.VBox([])

        add_row = W.HBox(
            [self._param_add_picker, self._btn_add_param],
            layout=W.Layout(flex_flow="row wrap"),
        )
        add_row.add_class("cadetgui-toolbar")

        self.root = W.VBox([add_row, self._param_header, self._param_box])

    def __len__(self) -> int:
        return len(self._added_keys)

    @staticmethod
    def _param_key(p: FittableParameter) -> _Key:
        return (p.owner, p.name, p.component_index)

    def _by_key(self) -> Dict[_Key, FittableParameter]:
        return {self._param_key(p): p for p in self.params}

    def rows(self) -> List[Tuple[int, float, float, float]]:
        """(index into `.params`, start, lower bound, upper bound) per added row, in add order."""
        index_of = {self._param_key(p): i for i, p in enumerate(self.params)}
        return [
            (index_of[key], start.value, lb.value, ub.value)
            for key, lb, ub, start in zip(
                self._added_keys, self._lb_fields, self._ub_fields, self._start_fields
            )
        ]

    def set_params(self, params: List[FittableParameter]) -> None:
        """Replace the available parameter set, dropping any added row whose identity is gone."""
        self._snapshot_row_state()
        valid_keys = {self._param_key(p) for p in params}
        self._added_keys = [k for k in self._added_keys if k in valid_keys]
        self.params = params
        self._refresh_added_rows()
        self._refresh_add_picker_options()

    def _snapshot_row_state(self) -> None:
        """Save each currently-rendered row's live field values into `_param_state`.

        Must run *before* `_added_keys` is mutated (append/remove/prune) --
        it zips the live fields against `_added_keys` as it stood when those
        fields were last built, so mutating the list first would silently
        pair each row's values with the wrong key.
        """
        for key, lb, ub, start in zip(
            self._added_keys, self._lb_fields, self._ub_fields, self._start_fields
        ):
            self._param_state[key] = {"lb": lb.value, "ub": ub.value, "start": start.value}

    def _refresh_add_picker_options(self) -> None:
        options = [
            (f"{p.label} = {p.current_value:.4g}", key)
            for key, p in self._by_key().items()
            if key not in self._added_keys
        ]
        self._param_add_picker.set_options(options)

    def _refresh_added_rows(self) -> None:
        """Rebuild one row (name label + start/lb/ub fields + remove button) per added parameter."""
        by_key = self._by_key()
        name_layout = W.Layout(width=self._NAME_WIDTH, overflow="hidden")
        field_layout = W.Layout(width=self._FIELD_WIDTH)
        remove_layout = W.Layout(width=self._REMOVE_WIDTH)
        self._lb_fields = []
        self._ub_fields = []
        self._start_fields = []
        self._remove_buttons = []
        rows = []
        for key in self._added_keys:
            p = by_key.get(key)
            if p is None:  # pragma: no cover -- already pruned by the caller
                continue
            state = self._param_state.setdefault(
                key, {"lb": p.lb, "ub": p.ub, "start": p.current_value}
            )
            lb_field = W.FloatText(value=state["lb"], layout=field_layout)
            ub_field = W.FloatText(value=state["ub"], layout=field_layout)
            start_field = W.FloatText(value=state["start"], layout=field_layout)
            remove_btn = W.Button(icon="times", layout=remove_layout)
            remove_btn.on_click(self._make_remove_handler(key))
            self._lb_fields.append(lb_field)
            self._ub_fields.append(ub_field)
            self._start_fields.append(start_field)
            self._remove_buttons.append(remove_btn)
            name_label = W.Label(f"{p.label} = {p.current_value:.4g}", layout=name_layout)
            rows.append(W.HBox([name_label, start_field, lb_field, ub_field, remove_btn]))
        self._param_box.children = tuple(rows)

    def _on_add_param(self, _btn: Any) -> None:
        key = self._param_add_picker.value
        if key is None or key in self._added_keys:
            return
        self._snapshot_row_state()
        self._added_keys.append(key)
        self._refresh_added_rows()
        self._refresh_add_picker_options()

    def _make_remove_handler(self, key: _Key) -> Any:
        def handler(_btn: Any) -> None:
            self._snapshot_row_state()
            if key in self._added_keys:
                self._added_keys.remove(key)
            self._param_state.pop(key, None)
            self._refresh_added_rows()
            self._refresh_add_picker_options()

        return handler
