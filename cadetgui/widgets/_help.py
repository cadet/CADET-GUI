from __future__ import annotations

import html
from typing import Mapping, Optional, Sequence

from ..characterization_guide import (
    EXPERIMENT_TYPES,
    GLOSSARY,
    GLOSSARY_ALIASES,
    Determined,
)

__all__ = [
    "term_html",
    "info_box_html",
    "checklist_html",
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


def info_box_html(title: str, body_html: str, *, open: bool = False) -> str:
    """Return a collapsible help box; `body_html` is inserted as is, `title` is escaped."""
    state = " open" if open else ""
    return (
        f"<details class='cadetgui-info'{state}>"
        f"<summary>{html.escape(title, quote=False)}</summary>"
        f"<div class='cadetgui-info-body'>{body_html}</div></details>"
    )


def checklist_html(items: Sequence[str]) -> str:
    """Return `items` as an escaped bullet list."""
    rows = "".join(f"<li>{html.escape(item, quote=False)}</li>" for item in items)
    return f"<ul class='cadetgui-checklist'>{rows}</ul>"


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table class='cadetgui-info-table'><tr>{head}</tr>{body}</table>"


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
    return _table(["Parameter", "Meaning", "Unit"], rows)


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
    return _table(headers, rows)
