from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional

import ipywidgets as W

from ... import run_store
from .._chrome import style_tag
from ..elements import ChoiceField, TextField

__all__ = ["RunHistoryWidget", "RunRecord"]


@dataclass
class RunRecord:
    """One entry in a RunHistoryWidget: a labeled result, or a labeled failure.

    `result` is `None` both for a failure and for an `ok` entry reloaded from
    a store that hasn't been hydrated back into a real result yet -- check
    `ok` to tell those two apart, not `result is None`.
    """

    label: str
    result: Any = None
    error: Optional[str] = None
    timestamp: dt.datetime = field(default_factory=dt.datetime.now)
    config_name: Optional[str] = None
    config_hash: Optional[str] = None
    run_id: Optional[str] = None

    @property
    def ok(self) -> bool:
        """Whether this run produced a result rather than an error."""
        return self.error is None


class RunHistoryWidget:
    """Chronological list of run results; pick one to revisit.

    Reusable across anything that produces multiple results over time — forward
    simulation runs today, estimation candidates / optimization solutions later.
    Callers `record()` a run and `add_listener()` to react when the user picks
    one to view.

    In-memory only unless `store_dir` is set (constructor kwarg, or the
    "Storage folder" field): a run history is only as project-scoped as the
    folder it's pointed at -- there is no other scoping concept, separating
    projects means using separate folders.
    """

    def __init__(self, *, store_dir: "Path | str | None" = None) -> None:
        self.runs: List[RunRecord] = []
        self._listeners: List[Callable[[RunRecord], None]] = []
        self._store_dir: Optional[Path] = None

        self._picker = ChoiceField(label="Run:", options=[])
        self._picker.observe(self._on_pick, names="selected_index")

        self._store_dir_field = TextField(label="Storage folder:", value="")
        self._btn_set_store_dir = W.Button(description="Set folder", icon="folder-open")
        self._store_dir_note = W.HTML(
            "<em>Leave blank to keep history in memory only (lost on kernel restart).</em>"
        )
        self._store_dir_note.add_class("cadetgui-note")
        self._btn_set_store_dir.on_click(self._on_set_store_dir)

        self.root = W.VBox(
            [
                W.HTML(style_tag()),
                self._picker,
                W.HBox([self._store_dir_field, self._btn_set_store_dir]),
                self._store_dir_note,
            ]
        )
        self.root.add_class("cadetgui-panel")

        self.store_dir = store_dir

    def add_listener(self, fn: Callable[[RunRecord], None]) -> None:
        """Register a callback fired with the picked RunRecord on every selection."""
        self._listeners.append(fn)

    def record(
        self,
        label: str,
        *,
        result: Any = None,
        error: Optional[str] = None,
        config_name: Optional[str] = None,
        config_hash: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> RunRecord:
        """Add a run to the history and select it.

        `run_id` should already be the id used to capture this run's raw
        output (see `run_store.run_output_path`) whenever the caller wants
        that output persisted too -- this only ever writes the metadata.
        """
        run = RunRecord(
            label=label, result=result, error=error,
            config_name=config_name, config_hash=config_hash, run_id=run_id,
        )
        self.runs.append(run)
        self._refresh_picker(select_index=len(self.runs) - 1)
        if self.store_dir is not None:
            self._persist(run)
        return run

    def clear(self) -> None:
        """Remove all recorded runs (in memory only -- does not touch the store)."""
        self.runs = []
        self._picker.set_options([])

    @property
    def selected(self) -> Optional[RunRecord]:
        """The currently picked run, if any."""
        return self._picker.value

    @property
    def store_dir(self) -> Optional[Path]:
        """The folder this history is scoped to, or None for in-memory only."""
        return self._store_dir

    @store_dir.setter
    def store_dir(self, value: "Path | str | None") -> None:
        """Point this history at a (new) folder, reloading its runs from it.

        Setting this has the exact same effect as the "Set folder" button --
        there is no separate scoping concept, a folder is a folder. A no-op
        if it's already pointed there: reloading unconditionally would wipe
        and re-fetch `self.runs` even when nothing changed, replacing an
        already-hydrated `RunRecord` with a fresh unhydrated stand-in whose
        re-selection then silently fails to re-trigger hydration (the picker's
        index doesn't change, so no selection event fires).
        """
        path = Path(value).expanduser().resolve() if value else None
        if path == self._store_dir:
            return
        if path is not None:
            path.mkdir(parents=True, exist_ok=True)
        self._store_dir = path
        self._store_dir_field.value = str(path) if path else ""
        self.runs = []
        if path is not None:
            self._load_from_store()
        else:
            self._picker.set_options([])

    def _describe(self, run: RunRecord) -> str:
        status = "ok" if run.ok else "failed"
        index = self.runs.index(run) + 1
        return f"#{index} — {run.timestamp:%H:%M:%S} — {run.label} — {status}"

    def _refresh_picker(self, *, select_index: Optional[int]) -> None:
        options = [(self._describe(r), r) for r in self.runs]
        self._picker.set_options(options, keep_value=False)
        if select_index is not None and self.runs:
            self._picker.selected_index = select_index

    def _persist(self, run: RunRecord) -> None:
        """Best-effort: a store-write failure must never break recording in memory."""
        try:
            state = run_store.save_run(
                run.run_id or run_store.new_run_id(),
                run.label,
                ok=run.ok,
                config_name=run.config_name,
                config_hash=run.config_hash,
                error=run.error,
                store_dir=self.store_dir,
            )
            run.run_id = state.run_id
        except Exception:  # noqa: BLE001
            pass

    def _load_from_store(self) -> None:
        """Populate from `store_dir`'s existing manifests, oldest first, result unhydrated."""
        for state in reversed(run_store.list_runs(store_dir=self.store_dir)):
            self.runs.append(
                RunRecord(
                    label=state.label,
                    error=state.error,
                    timestamp=dt.datetime.fromisoformat(state.timestamp),
                    config_name=state.config_name,
                    config_hash=state.config_hash,
                    run_id=state.run_id,
                )
            )
        self._refresh_picker(select_index=len(self.runs) - 1 if self.runs else None)

    def _on_set_store_dir(self, _btn: Any) -> None:
        try:
            self.store_dir = self._store_dir_field.value.strip() or None
        except Exception:  # noqa: BLE001
            pass

    def _on_pick(self, change: dict) -> None:
        if change.get("name") != "selected_index":
            return
        run = self._picker.value
        if run is None:
            return
        for fn in list(self._listeners):
            fn(run)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
