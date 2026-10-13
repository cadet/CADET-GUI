from __future__ import annotations

import html
from typing import Mapping, Optional, Sequence

from ..characterization.guide import (
    EXPERIMENT_TYPES,
    GLOSSARY,
    GLOSSARY_ALIASES,
    Determined,
)
from .ui.html import table_html

__all__ = [
    "term_html",
    "determines_table_html",
    "experiments_table_html",
]


def term_html(term: str, label: Optional[str] = None) -> str:
    """Return `label` (default `term`) with the glossary definition of `term` as a hover tip.

    Terms in `GLOSSARY_ALIASES` resolve to their current entry; unknown terms render as
    plain escaped text.
    """
    text = html.escape(label if label is not None else term, quote=False)
    term = GLOSSARY_ALIASES.get(term, GLOSSARY_ALIASES.get(term.lower(), term))
    definition = GLOSSARY.get(term) or GLOSSARY.get(term.lower())
    if not definition:
        return text
    tip = html.escape(definition, quote=True)
    return f"<span class='cadetgui-term' tabindex='0' data-tip=\"{tip}\">{text}</span>"


def determines_table_html(determines: Sequence[Determined]) -> str:
    """Return a Parameter / Meaning / Unit table for a step's determined parameters."""
    rows = [
        (
            f"<b>{html.escape(d.name, quote=False)}</b>",
            html.escape(d.meaning, quote=False),
            f"<span class='cadetgui-info-unit'>{html.escape(d.unit, quote=False)}</span>",
        )
        for d in determines
    ]
    return table_html(["Parameter", "Meaning", "Unit"], rows, css_class="cadetgui-info-table")


def experiments_table_html(
    type_ids: Sequence[str], attached: Optional[Mapping[str, Sequence[str]]] = None
) -> str:
    """Return an experiments table; with `attached`, add each type's measurements."""
    headers = ["Experiment", "Detector", "Probe", "What you run"]
    if attached is not None:
        headers.append("Measurements")
    rows = []
    for type_id in type_ids:
        experiment = EXPERIMENT_TYPES[type_id]
        row = [
            f"<b>{html.escape(experiment.label, quote=False)}</b>",
            html.escape(experiment.detector, quote=False),
            html.escape(experiment.probe_role, quote=False),
            f"<small>{html.escape(experiment.what_you_run, quote=False)}</small>",
        ]
        if attached is not None:
            names = attached.get(type_id) or ()
            row.append(
                html.escape(", ".join(names), quote=False) if names
                else "<em class='cadetgui-info-missing'>none yet</em>"
            )
        rows.append(row)
    return table_html(headers, rows, css_class="cadetgui-info-table")
