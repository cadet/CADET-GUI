from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

import ipywidgets as W

from .._chrome import style_tag
from ..elements import ChoiceField

__all__ = ["RunHistoryWidget", "RunRecord"]


@dataclass
class RunRecord:
    """One entry in a RunHistoryWidget: a labeled result, or a labeled failure."""

    label: str
    result: Any = None
    error: Optional[str] = None
    timestamp: dt.datetime = field(default_factory=dt.datetime.now)
    config_name: Optional[str] = None
    config_hash: Optional[str] = None

    @property
    def ok(self) -> bool:
        """Whether this run produced a result rather than an error."""
        return self.error is None


class RunHistoryWidget:
    """Chronological list of run results; pick one to revisit.

    Reusable across anything that produces multiple results over time — forward
    simulation runs today, estimation candidates / optimization solutions later
    (see ai-docs/REQUIREMENTS.md's "Next widgets" gap analysis). Callers `record()`
    a run and `add_listener()` to react when the user picks one to view.
    """

    def __init__(self) -> None:
        self.runs: List[RunRecord] = []
        self._listeners: List[Callable[[RunRecord], None]] = []

        self._picker = ChoiceField(label="Run:", options=[])
        self._picker.observe(self._on_pick, names="selected_index")

        self.root = W.VBox([W.HTML(style_tag()), self._picker])
        self.root.add_class("cadetgui-panel")

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
    ) -> RunRecord:
        """Add a run to the history and select it."""
        run = RunRecord(
            label=label, result=result, error=error,
            config_name=config_name, config_hash=config_hash,
        )
        self.runs.append(run)
        options = [(self._describe(r), r) for r in self.runs]
        self._picker.set_options(options, keep_value=False)
        self._picker.selected_index = len(self.runs) - 1  # newest, not set_options' default-first
        return run

    def clear(self) -> None:
        """Remove all recorded runs."""
        self.runs = []
        self._picker.set_options([])

    @property
    def selected(self) -> Optional[RunRecord]:
        """The currently picked run, if any."""
        return self._picker.value

    def _describe(self, run: RunRecord) -> str:
        status = "ok" if run.ok else "failed"
        index = self.runs.index(run) + 1
        return f"#{index} — {run.timestamp:%H:%M:%S} — {run.label} — {status}"

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
