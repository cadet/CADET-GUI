"""Experiment-type page of the add-measurement stepper."""

from __future__ import annotations

import html
from typing import Any, Callable, List, Optional, Tuple

import ipywidgets as W

from ....characterization.guide import (
    CHAIN_BY_ID,
    DEFAULT_CHAIN,
    EXPERIMENT_TYPES,
    ExperimentType,
)
from ....instrument.recipes import template_options
from ....io.configuration_store import ConfigurationState
from ...elements import ChoiceField, SelectableTable
from ...ui.layout import note, row
from ..help import term_html
from .labels import detector_hint, observation_label

__all__ = ["ExperimentTypePage", "OTHER"]

OTHER = "__other__"


class ExperimentTypePage:
    """Table of experiment types (plus "Other"), the picked one's help and Other's template."""

    def __init__(
        self, base_recipe: Callable[[], Tuple[Optional[ConfigurationState], str]]
    ) -> None:
        self._base_recipe = base_recipe
        self.table = SelectableTable(
            columns=["Feeds step", "Experiment type", "Detector"],
            empty_text="No experiment types.",
        )
        self.help = W.HTML()
        self.other_template = ChoiceField(label="Process template:")
        self.other_template_box = W.VBox(
            [
                row(self.other_template),
                note(
                    "Runs added as “Other” get no experiment type, so pick the process "
                    "(method) the run followed. It starts with the template's default timing "
                    "and concentrations; change them under Advanced after adding."
                ),
            ],
            layout=W.Layout(display="none"),
        )
        self.table.observe(lambda _c: self.show_help(), names="selected_index")
        self.root = W.VBox([
            note("What did you run? The experiment type sets the flow path, process "
                 "template and observation point, and which characterization step the "
                 "measurement feeds. Types matching the channel's detector are marked."),
            self.table,
            self.help,
            self.other_template_box,
        ])

    @property
    def experiment_type(self) -> Optional[ExperimentType]:
        """The picked experiment type (`None` for 'Other' or no choice)."""
        return EXPERIMENT_TYPES.get(self.table.value or "")

    def reset(self) -> None:
        """Forget the template picked for 'Other'."""
        self.other_template.set_options([], keep_value=False)

    def fill(self, channel: Optional[str], select: Optional[str]) -> None:
        """List all experiment types, marking those matching `channel`; select `select`."""
        hint = detector_hint(channel or "")
        options: List[Tuple[str, str]] = []
        rows: List[List[Any]] = []
        chained = [t for g in DEFAULT_CHAIN for t in g.experiment_types]
        unchained = [t for t in EXPERIMENT_TYPES if t not in chained]
        for type_id in (*chained, *unchained):
            experiment_type = EXPERIMENT_TYPES[type_id]
            guide = CHAIN_BY_ID.get(experiment_type.step_id)
            detector: Any = experiment_type.detector
            if hint is not None and hint == experiment_type.detector:
                detector = (f"{experiment_type.detector} · matches channel", "ok")
            options.append((experiment_type.label, type_id))
            rows.append([guide.title if guide else "Not assigned to a step",
                         experiment_type.label, detector])
        options.append(("Other: set up everything by hand", OTHER))
        rows.append(["Not assigned to a step", "Other: set up everything by hand", "–"])
        self.table.set_options(options, rows=rows, select_none=True)
        if select is not None:
            self.table.value = select
        self.show_help()

    def show_help(self) -> None:
        """Describe the picked type; for 'Other', offer the process templates."""
        type_id = self.table.value
        self.other_template_box.layout.display = "" if type_id == OTHER else "none"
        if type_id is None:
            self.help.value = ""
            return
        if type_id == OTHER:
            self._fill_other_templates()
            self.help.value = (
                "<p class='cadetgui-note'>The run uses your System setup with the process "
                "template picked below. Set the observation point, probe and everything "
                "else under Advanced after adding. The measurement is not assigned to a "
                "step until you set an experiment type.</p>"
            )
            return
        experiment_type = EXPERIMENT_TYPES[type_id]
        guide = CHAIN_BY_ID.get(experiment_type.step_id)
        parts = [
            f"<p><b>What you run:</b> {html.escape(experiment_type.what_you_run)}</p>",
            f"<p><b>Feeds step:</b> {html.escape(guide.title if guide else 'none')} · "
            f"<b>{term_html('probe', 'Probe')}:</b> {html.escape(experiment_type.probe_role)}"
            f" · <b>{term_html('observation point', 'Observation point')}:</b> "
            f"{html.escape(observation_label(experiment_type.solution_path))} "
            f"({html.escape(experiment_type.detector)})</p>",
        ]
        if experiment_type.help:
            parts.append(f"<p class='cadetgui-note'>{html.escape(experiment_type.help)}</p>")
        self.help.value = "".join(parts)

    def _fill_other_templates(self) -> None:
        base, _ = self._base_recipe()
        if base is None:
            self.other_template.set_options([], keep_value=False)
            return
        keep = self.other_template.value
        options = template_options(base)
        self.other_template.set_options(options, keep_value=False)
        values = [v for _, v in options]
        self.other_template.value = keep if keep in values else base.template_key
