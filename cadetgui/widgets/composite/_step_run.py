"""Background fit, progress chart and live fit plot of a characterization step."""

from __future__ import annotations

import html
import threading
import time
from typing import Any, Dict, List, Optional

import ipywidgets as W
import numpy as np

from ...characterization import runner
from ...characterization.parameter_store import ParameterStore
from ...characterization.runner import Candidate, StepSetup, current_best_average
from .._status import status_html
from ..elements import ChromatogramChart, LineChart
from ._step_results import _preview_series, _preview_title


class _StepRun:
    """Run mechanics of `CharacterizationStepWidget`: fit thread, progress, live fit plot.

    The host provides `running` and `_finish(start)`.
    """

    _TICK_SECONDS = 0.5

    def _init_run(self) -> None:
        self._run_done = threading.Event()
        self._cancel_event = threading.Event()
        self._progress: Dict[str, Any] = {}
        self._ticker: Optional[threading.Thread] = None
        self._run_setup: Optional[StepSetup] = None
        self._run_prior: Optional[ParameterStore] = None
        self._live_busy = threading.Lock()
        self._live_write = threading.Lock()
        self._live_token = 0
        self._live_generation = 0
        self._live_built: Optional[Any] = None
        self._live_thread: Optional[threading.Thread] = None
        self.live_update_seconds: List[float] = []

        self._btn_cancel = W.Button(
            description="Cancel", icon="stop", button_style="danger",
            layout=W.Layout(display="none"),
        )
        self._btn_cancel.on_click(lambda _b: self.cancel())
        self._progress_label = W.HTML()
        self._progress_chart = LineChart(
            view_width=520, view_height=240, x_label="Generation", x_name="generation",
            x_unit="", y_label="Best objective so far", empty_text="No generations yet",
        )
        self._progress_title = W.HTML()
        self.live_plot = W.Checkbox(
            value=True, description="Live fit plot", indent=False,
            tooltip="Show the current best fit while the run is going.",
            layout=W.Layout(width="auto"),
        )
        self._live_note = W.HTML()
        self._live_title = W.HTML()
        self._live_charts = W.HBox(layout=W.Layout(flex_flow="row wrap"))
        self._live_chart_widgets: List[tuple[W.HTML, ChromatogramChart]] = []
        self._progress_box = W.VBox([
            self._progress_title,
            self._progress_chart,
            self._live_title,
            self._live_charts,
        ], layout=W.Layout(display="none"))

    def _launch(self, setup: StepSetup, prior: ParameterStore, name: str, kwargs: dict) -> None:
        """Fit `setup` on a background thread and tick the progress until it finishes."""
        self._btn_cancel.layout.display = ""
        self._btn_cancel.disabled = False
        self._btn_cancel.description = "Cancel"
        self._progress_chart.series = []
        self._progress_title.value = "<b>Best so far per objective</b>"
        self._progress_box.layout.display = ""
        self._run_done.clear()
        self._cancel_event.clear()
        self._progress = {"optimizer": None, "result": None, "error": None}
        start = time.monotonic()
        threading.Thread(
            target=self._work, args=(setup, prior, name, kwargs), daemon=True
        ).start()
        self._ticker = threading.Thread(target=self._tick, args=(start,), daemon=True)
        self._ticker.start()

    def _reset_live(self, setup: StepSetup) -> None:
        """Drop pending live updates and make one live chart per measurement."""
        with self._live_write:
            self._live_token += 1
        self._live_generation = 0
        self._live_built = None
        self.live_update_seconds = []
        self._live_chart_widgets = [
            (
                W.HTML(f"<b>{html.escape(c.name)}</b>"),
                ChromatogramChart(
                    view_width=420, view_height=240, y_label="Signal",
                    empty_text="Waiting for the first generation",
                ),
            )
            for c in setup.comparisons
        ]
        self._live_charts.children = [W.VBox(list(pair)) for pair in self._live_chart_widgets]
        self._live_title.value = ""
        self._live_note.value = ""

    def _work(self, setup: StepSetup, prior: ParameterStore, name: str, kwargs: dict) -> None:
        try:
            self._progress["result"] = runner.run(
                setup, prior, optimizer_name=name, optimizer_kwargs=kwargs,
                cancel_event=self._cancel_event,
                on_optimizer_ready=lambda opt: self._progress.update(optimizer=opt),
            )
        except Exception as exc:  # noqa: BLE001 -- shown to the user
            self._progress["error"] = str(exc)
        self._run_done.set()

    def _tick(self, start: float) -> None:
        shown = 0
        while not self._run_done.wait(timeout=self._TICK_SECONDS):
            shown = self._update_progress(start, shown)
        self._update_progress(start, -1)
        self._finish(start)

    def _update_progress(self, start: float, shown: int) -> int:
        optimizer = self._progress.get("optimizer")
        results = getattr(optimizer, "results", None)
        populations = list(results.populations) if results is not None else []
        n_gen = len(populations)
        text = f"{time.monotonic() - start:.0f}s elapsed · generation {n_gen}"
        if n_gen and n_gen != shown:
            best = np.minimum.accumulate(np.array([p.f_min for p in populations]), axis=0)
            names = self._run_setup.objective_names
            generations = list(range(1, n_gen + 1))
            self._progress_chart.series = [
                {"name": name, "times": generations, "values": [float(v) for v in best[:, i]]}
                for i, name in enumerate(names)
            ]
            self._progress["best"] = ", ".join(
                f"{name} {best[-1, i]:.3g}" for i, name in enumerate(names)
            )
            if shown >= 0 and self.live_plot.value:
                candidate = current_best_average(optimizer)
                if candidate is not None:
                    self._start_live_update(candidate, n_gen)
        if self._progress.get("best"):
            text += f" · best {self._progress['best']}"
        self._progress_label.value = f"<em>{html.escape(text)}</em>"
        return n_gen

    def _start_live_update(self, candidate: Candidate, generation: int) -> bool:
        """Simulate `candidate` for the live plot unless an update is still running."""
        if generation <= self._live_generation or not self._live_busy.acquire(blocking=False):
            return False
        self._live_generation = generation
        self._live_thread = threading.Thread(
            target=self._live_update, args=(candidate, generation, self._live_token),
            name="live-fit-plot", daemon=True,
        )
        self._live_thread.start()
        return True

    def _live_update(self, candidate: Candidate, generation: int, token: int) -> None:
        """Simulate every measurement at `candidate` on processes built for this plot only."""
        try:
            began = time.monotonic()
            setup, prior = self._run_setup, self._run_prior
            if self._live_built is None:
                self._live_built = runner.build(setup, prior)
            store = runner.posterior(setup, self._live_built, prior, candidate)
            previews = [c.evaluate(store) for c in setup.comparisons]
            seconds = time.monotonic() - began
            self.live_update_seconds.append(seconds)
            with self._live_write:
                if token == self._live_token:
                    self._show_live(
                        previews,
                        f"Signal being fitted: generation {generation}, best-average "
                        f"candidate (simulated in {seconds:.1f} s)",
                    )
        except Exception as exc:  # noqa: BLE001 -- the fit itself is unaffected
            with self._live_write:
                if token == self._live_token:
                    self._live_note.value = status_html("warn", f"Live fit plot: {exc}")
        finally:
            self._live_busy.release()

    def _show_live(self, previews: list, title: str) -> None:
        for (label, chart), preview in zip(self._live_chart_widgets, previews):
            label.value = _preview_title(preview)
            chart.series = _preview_series(preview)
        self._live_title.value = f"<b>{html.escape(title)}</b>"
        self._live_note.value = ""

    def cancel(self) -> None:
        """Stop the run after the current generation; the last full front is kept."""
        if not self.running:
            return
        self._cancel_event.set()
        self._btn_cancel.disabled = True
        self._btn_cancel.description = "Cancelling… (finishing generation)"

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Block until a started run and its last live-plot update have finished."""
        deadline = None if timeout is None else time.monotonic() + timeout
        for attribute in ("_ticker", "_live_thread"):
            thread = getattr(self, attribute)
            if thread is not None:
                thread.join(None if deadline is None else max(deadline - time.monotonic(), 0))
                if thread.is_alive():
                    return False
        return True
