from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Callable, Dict, List, Optional

import ipywidgets as W

from ... import parameter_history_store
from .._chrome import style_tag
from ..elements import SelectableTable

__all__ = ["ParameterHistoryWidget", "ParameterPushRecord"]

ParameterPushRecord = parameter_history_store.ParameterPushRecordState


class ParameterHistoryWidget:
    """Chronological log of "Push to Configuration" events with their provenance.

    `record()` appends a push and, when `store_dir` is set, persists it. Picking a push
    only displays it; "Re-apply" is the one action that fires the callbacks registered
    with `add_reapply_listener`, which know where each value is written.
    """

    def __init__(self, *, store_dir: "Path | str | None" = None) -> None:
        self.pushes: List[ParameterPushRecord] = []
        self._reapply_listeners: List[Callable[[ParameterPushRecord], None]] = []
        self._store_dir: Optional[Path] = None

        self._picker = SelectableTable(
            label="Pushes",
            columns=["#", "Time", "Stage", "Parameters"],
            empty_text="No pushes yet.",
        )
        self._picker.observe(self._on_pick, names="selected_index")

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

    def add_reapply_listener(self, fn: Callable[[ParameterPushRecord], None]) -> None:
        """Register a callback fired with the picked push when "Re-apply" is clicked."""
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
            parameter_history_store.save_push(
                push.push_id, push.stage, push.values,
                dataset_labels=push.dataset_labels, optimizer_name=push.optimizer_name,
                objective=push.objective, config_name=push.config_name,
                config_hash=push.config_hash, store_dir=self.store_dir,
            )
        return push

    @property
    def selected(self) -> Optional[ParameterPushRecord]:
        """The currently picked push, if any."""
        return self._picker.value

    @property
    def store_dir(self) -> Optional[Path]:
        """The folder this history is persisted to, or None for in-memory only."""
        return self._store_dir

    @store_dir.setter
    def store_dir(self, value: "Path | str | None") -> None:
        """Point this history at a folder and load its pushes, or None for in-memory only."""
        path = Path(value).expanduser().resolve() if value else None
        if path == self._store_dir:
            return
        if path is not None:
            path.mkdir(parents=True, exist_ok=True)
        self._store_dir = path
        # Newest first on disk, oldest first here.
        self.pushes = (
            list(reversed(parameter_history_store.list_pushes(store_dir=path))) if path else []
        )
        self._refresh_picker(select_index=len(self.pushes) - 1 if self.pushes else None)

    def _refresh_picker(self, *, select_index: Optional[int]) -> None:
        options, rows = [], []
        for index, push in enumerate(self.pushes, start=1):
            time, names = push.timestamp[11:19], ", ".join(sorted(push.values))
            options.append((f"#{index} — {time} — {push.stage} — {names}", push))
            rows.append([str(index), time, push.stage, names])
        self._picker.set_options(options, rows=rows, keep_value=False)
        if select_index is not None and self.pushes:
            self._picker.selected_index = select_index

    def _render_details(self, push: Optional[ParameterPushRecord]) -> None:
        if push is None:
            self._details.value = ""
            self._btn_reapply.layout.display = "none"
            return
        rows = "".join(
            f"<tr><td>{name}</td><td>{value:.4g}</td></tr>"
            for name, value in sorted(push.values.items())
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

    def _on_pick(self, change: dict) -> None:
        if change.get("name") == "selected_index":
            self._render_details(self._picker.value)

    def _on_reapply_click(self, _btn: object) -> None:
        push = self.selected
        if push is not None:
            for fn in self._reapply_listeners:
                fn(push)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
