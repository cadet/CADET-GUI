from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import ipywidgets as W

from ... import parameter_history_store
from .._chrome import style_tag
from ..elements import ChoiceField, TextField

__all__ = ["ParameterHistoryWidget", "ParameterPushRecord"]

ParameterPushRecord = parameter_history_store.ParameterPushRecordState
"""One entry in a ParameterHistoryWidget -- re-exported so callers don't also
need to import `cadetgui.parameter_history_store` directly."""


class ParameterHistoryWidget:
    """Chronological, provenance-carrying log of "Push to Configuration" events.

    Same shape as `RunHistoryWidget` (widgets/composite/run_history.py) --
    a `ChoiceField` picker over recorded entries, optional folder
    persistence, `add_listener`/`store_dir` following the same conventions
    -- deliberately not built as a subclass of it: `RunHistoryWidget` is
    exercised by tests that reach into its private structure directly (same
    situation `OptimizerRunnerPanel` hit with `ParameterEstimationWidget`,
    see its own docstring), so retrofitting it onto a shared base isn't
    worth the risk for what's a genuinely small amount of duplicated
    picker/folder-scoping code. The persistence layer *is* shared --
    `cadetgui._record_store` backs both `run_store.py` and
    `parameter_history_store.py`.

    Unlike a run, a push has no separate "raw output" to lazily hydrate --
    `ParameterPushRecord` (`parameter_history_store.ParameterPushRecordState`)
    is already the complete record, so there's no `ok`/ `result is None`
    distinction to make here.

    `record()` both appends to `.pushes` and (best-effort) persists.
    `add_listener` fires with the picked record on every selection --
    harmless, since picking only ever changes what's *displayed*. Re-
    applying a past push's values is a separate, deliberate action:
    register via `add_reapply_listener`, fired only when "Re-apply" is
    clicked, matching the "never silently overwrite" rule the rest of
    cadetgui's accept/push flows already follow -- this widget has no
    domain knowledge of *where* a value writes back to (that's
    `CharacterizationWidget._write_fitted_values`'s job; see
    `CharacterizationWorkbenchWidget._on_reapply` for the routing).
    """

    def __init__(
        self,
        *,
        store_dir: "Path | str | None" = None,
        on_manual_store_dir_change: Optional[Callable[[Optional[Path]], None]] = None,
    ) -> None:
        self.pushes: List[ParameterPushRecord] = []
        self._listeners: List[Callable[[ParameterPushRecord], None]] = []
        self._reapply_listeners: List[Callable[[ParameterPushRecord], None]] = []
        self._store_dir: Optional[Path] = None
        self._on_manual_store_dir_change = on_manual_store_dir_change

        self._picker = ChoiceField(label="Push:", options=[])
        self._picker.observe(self._on_pick, names="selected_index")

        self._store_dir_field = TextField(label="Storage folder:", value="")
        self._btn_set_store_dir = W.Button(description="Set folder", icon="folder-open")
        self._btn_set_store_dir.on_click(self._on_set_store_dir)

        self._details = W.HTML()
        self._btn_reapply = W.Button(
            description="Re-apply", icon="undo", layout=W.Layout(display="none")
        )
        self._btn_reapply.on_click(self._on_reapply_click)

        self.root = W.VBox(
            [W.HTML(style_tag()), self._picker, self._details, self._btn_reapply]
        )
        self.root.add_class("cadetgui-panel")

        self.store_dir = store_dir

    def add_listener(self, fn: Callable[[ParameterPushRecord], None]) -> None:
        """Register a callback fired with the picked record on every selection."""
        self._listeners.append(fn)

    def add_reapply_listener(self, fn: Callable[[ParameterPushRecord], None]) -> None:
        """Register a callback fired with the picked record when "Re-apply" is clicked."""
        self._reapply_listeners.append(fn)

    def record(
        self,
        stage: str,
        values: Dict[str, float],
        *,
        dataset_labels: Optional[List[str]] = None,
        optimizer_name: Optional[str] = None,
        objective: Optional[float] = None,
        config_name: Optional[str] = None,
        config_hash: Optional[str] = None,
    ) -> ParameterPushRecord:
        """Add a push to the history and select it."""
        push = ParameterPushRecord(
            push_id=parameter_history_store.new_push_id(),
            stage=stage,
            timestamp=dt.datetime.now().isoformat(),
            values=dict(values),
            dataset_labels=list(dataset_labels or []),
            optimizer_name=optimizer_name,
            objective=objective,
            config_name=config_name,
            config_hash=config_hash,
        )
        self.pushes.append(push)
        self._refresh_picker(select_index=len(self.pushes) - 1)
        if self.store_dir is not None:
            self._persist(push)
        return push

    def clear(self) -> None:
        """Remove all recorded pushes (in memory only -- does not touch the store)."""
        self.pushes = []
        self._picker.set_options([])

    @property
    def selected(self) -> Optional[ParameterPushRecord]:
        """The currently picked push, if any."""
        return self._picker.value

    @property
    def store_dir(self) -> Optional[Path]:
        """The folder this history is scoped to, or None for in-memory only."""
        return self._store_dir

    @store_dir.setter
    def store_dir(self, value: "Path | str | None") -> None:
        """Point this history at a (new) folder, reloading its pushes from it.

        Same behavior/rationale as `RunHistoryWidget.store_dir`'s setter --
        a no-op if already pointed there, so re-selecting an
        already-loaded push doesn't need to survive a needless reload.
        """
        path = Path(value).expanduser().resolve() if value else None
        if path == self._store_dir:
            return
        if path is not None:
            path.mkdir(parents=True, exist_ok=True)
        self._store_dir = path
        self._store_dir_field.value = str(path) if path else ""
        self.pushes = []
        if path is not None:
            self._load_from_store()
        else:
            self._picker.set_options([])

    def _describe(self, push: ParameterPushRecord) -> str:
        index = self.pushes.index(push) + 1
        param_names = ", ".join(sorted(push.values))
        return f"#{index} — {push.timestamp[11:19]} — {push.stage} — {param_names}"

    def _refresh_picker(self, *, select_index: Optional[int]) -> None:
        options = [(self._describe(p), p) for p in self.pushes]
        self._picker.set_options(options, keep_value=False)
        if select_index is not None and self.pushes:
            self._picker.selected_index = select_index

    def _render_details(self, push: Optional[ParameterPushRecord]) -> None:
        if push is None:
            self._details.value = ""
            self._btn_reapply.layout.display = "none"
            return
        rows = "".join(
            f"<tr><td>{path}</td><td>{value:.4g}</td></tr>"
            for path, value in sorted(push.values.items())
        )
        datasets = ", ".join(push.dataset_labels) or "—"
        objective = f"{push.objective:.4g}" if push.objective is not None else "—"
        self._details.value = (
            f"<div><strong>Stage:</strong> {push.stage} &nbsp; "
            f"<strong>Datasets:</strong> {datasets} &nbsp; "
            f"<strong>Optimizer:</strong> {push.optimizer_name or '—'} &nbsp; "
            f"<strong>Objective:</strong> {objective}</div>"
            f"<table><tr><th>Parameter</th><th>Value</th></tr>{rows}</table>"
        )
        self._btn_reapply.layout.display = ""

    def _persist(self, push: ParameterPushRecord) -> None:
        """Best-effort: a store-write failure must never break recording in memory."""
        try:
            parameter_history_store.save_push(
                push.push_id, push.stage, push.values,
                dataset_labels=push.dataset_labels, optimizer_name=push.optimizer_name,
                objective=push.objective, config_name=push.config_name,
                config_hash=push.config_hash, store_dir=self.store_dir,
            )
        except Exception:  # noqa: BLE001
            pass

    def _load_from_store(self) -> None:
        """Populate from `store_dir`'s existing manifests, oldest first."""
        self.pushes = list(
            reversed(parameter_history_store.list_pushes(store_dir=self.store_dir))
        )
        self._refresh_picker(select_index=len(self.pushes) - 1 if self.pushes else None)

    def _on_set_store_dir(self, _btn: Any) -> None:
        try:
            self.store_dir = self._store_dir_field.value.strip() or None
        except Exception:  # noqa: BLE001
            return
        if self._on_manual_store_dir_change is not None:
            self._on_manual_store_dir_change(self.store_dir)

    def _on_pick(self, change: dict) -> None:
        if change.get("name") != "selected_index":
            return
        push = self._picker.value
        self._render_details(push)
        if push is None:
            return
        for fn in list(self._listeners):
            fn(push)

    def _on_reapply_click(self, _btn: Any) -> None:
        push = self.selected
        if push is None:
            return
        for fn in list(self._reapply_listeners):
            fn(push)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
