"""HTML blocks of a characterization step: the "About this step" card and the best values."""

from __future__ import annotations

import html
from typing import Dict, List

from ....characterization.guide import ChainStepGuide
from ....characterization.runner import Candidate, StepSetup
from ....characterization.study import Study
from ...ui.format import unit_html
from ...ui.html import info_box_html, table_html
from ..help import determines_table_html, experiments_table_html, term_html
from ..setup import step_diagrams_html


def components_html(study: Study, setup: StepSetup) -> str:
    """Return a line naming the components this step's measurements use, with roles."""
    names = list(dict.fromkeys(c.probe for c in setup.comparisons if c.probe))
    if not names:
        return ""
    parts = []
    for name in names:
        component = study.component(name)
        role = f" ({component.role})" if component is not None else " (not declared)"
        parts.append(html.escape(name + role))
    return (
        "<p><b>" + term_html("component", "Components") + ":</b> " + ", ".join(parts)
        + ". <small>Values this step fits are stored under these names; a later step "
        "reuses them only for the same component.</small></p>"
    )


def header_html(
    guide: ChainStepGuide, setup: StepSetup, *, open: bool, components: str = ""
) -> str:
    """Return the step's lab-language description: purpose, experiments, advice."""
    body = (
        f"<p>{html.escape(guide.purpose)}</p>"
        + components +
        f"<b>Determines</b>{determines_table_html(guide.determines)}"
        f"<b>Experiments that feed it</b>{experiments_table_html(guide.experiment_types)}"
        + "<p><small>Lab checks the software cannot do for this step are in the Guide."
        "</small></p>"
        + info_box_html("Reading the results", f"<p>{html.escape(guide.reading_results)}</p>")
        + step_diagrams_html(guide, setup.comparisons)
    )
    return info_box_html(f"About this step: {guide.title}", body, open=open)


def best_values_html(
    names: List[str], units: Dict[str, str], candidate: Candidate, setup: StepSetup
) -> str:
    """Return a candidate's variable values and objectives as two tables."""
    if len(names) != len(candidate.x):
        names = [f"x{i + 1}" for i in range(len(candidate.x))]
    variables = [
        [html.escape(name), f"{value:.4g}", unit_html(units.get(name, ""))]
        for name, value in zip(names, candidate.x)
    ]
    objectives = [
        [html.escape(c.name), f"{value:.4g}", term_html(c.metric)]
        for c, value in zip(setup.comparisons, candidate.f)
    ]
    info = "cadetgui-info-table"
    return (
        f"<div><b>{term_html('best average', 'Best average')} of the final front</b></div>"
        "<div style='display:flex;flex-wrap:wrap;gap:24px'>"
        + table_html(["Parameter", "Value", "Unit"], variables, css_class=info)
        + table_html(["Measurement", "Error", "Metric"], objectives, css_class=info)
        + "</div>"
    )
