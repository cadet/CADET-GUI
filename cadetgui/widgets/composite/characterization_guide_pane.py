from __future__ import annotations

import html
import re
from typing import List

import ipywidgets as W

from ...characterization_guide import (
    CHAIN_BY_ID,
    DEFAULT_CHAIN,
    EXPERIMENT_TYPES,
    GLOSSARY,
    WORKFLOW_GUIDE,
)
from .._chrome import style_tag
from .._help import checklist_html

__all__ = ["CharacterizationGuideWidget", "markdown_html"]

_ORDERED = re.compile(r"^\d+\.\s+")
_BULLET = re.compile(r"^[-*]\s+")
_CELL = "padding:4px 8px;border-bottom:1px solid var(--cg-border);vertical-align:top"


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", text)


def markdown_html(text: str) -> str:
    """Convert the small markdown subset the guide uses: headings, paragraphs, lists, bold."""
    out: List[str] = []
    paragraph: List[str] = []
    items: List[List[str]] = []
    list_tag = ""

    def flush() -> None:
        nonlocal list_tag
        if paragraph:
            out.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()
        if items:
            body = "".join(f"<li>{_inline(' '.join(item))}</li>" for item in items)
            out.append(f"<{list_tag}>{body}</{list_tag}>")
            items.clear()
            list_tag = ""

    for raw in text.splitlines():
        line = raw.strip()
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        marker = _ORDERED.match(line) or _BULLET.match(line)
        if not line:
            flush()
        elif heading:
            flush()
            level = min(len(heading.group(1)) + 2, 6)
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif marker:
            tag = "ol" if _ORDERED.match(line) else "ul"
            if paragraph or (items and tag != list_tag):
                flush()
            list_tag = tag
            items.append([line[marker.end():]])
        elif items and raw[:1].isspace():
            items[-1].append(line)
        else:
            if items:
                flush()
            paragraph.append(line)
    flush()
    return "".join(out)


def _glossary_html() -> str:
    rows = "".join(
        f"<dt><b>{html.escape(term)}</b></dt><dd>{html.escape(definition)}</dd>"
        for term, definition in sorted(GLOSSARY.items(), key=lambda kv: kv[0].lower())
    )
    return f"<dl class='cadetgui-glossary'>{rows}</dl>"


def _table(header: List[str], rows: List[List[str]]) -> str:
    head = "".join(f"<th style='{_CELL};text-align:left'>{h}</th>" for h in header)
    body = "".join(
        "<tr>" + "".join(f"<td style='{_CELL}'>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"<table style='border-collapse:collapse;width:100%'><tr>{head}</tr>{body}</table>"


def _experiment_types_html() -> str:
    rows = [
        [
            f"<b>{html.escape(t.label)}</b>",
            html.escape(CHAIN_BY_ID[t.step_id].title if t.step_id in CHAIN_BY_ID else t.step_id),
            html.escape(t.what_you_run),
            html.escape(t.detector),
        ]
        for t in EXPERIMENT_TYPES.values()
    ]
    return _table(["Experiment type", "Feeds step", "What you run", "Detector"], rows)


def _chain_html() -> str:
    rows = [
        [
            f"{i}. <b>{html.escape(g.title)}</b>",
            html.escape(g.purpose),
            "<br>".join(html.escape(f"{d.name} ({d.unit})") for d in g.determines),
        ]
        for i, g in enumerate(DEFAULT_CHAIN, start=1)
    ]
    return _table(["Step", "Purpose", "Determines"], rows)


def _lab_checks_html() -> str:
    return "".join(
        f"<b>{i}. {html.escape(g.title)}</b>{checklist_html(g.advice)}"
        for i, g in enumerate(DEFAULT_CHAIN, start=1) if g.advice
    )


class CharacterizationGuideWidget:
    """Read-only help pane: workflow, chain, lab checks, optimizers, experiment types, glossary."""

    def __init__(self) -> None:
        def section(title: str, body: str) -> W.HTML:
            box = W.HTML(f"<div class='cadetgui-section-title'>{html.escape(title)}</div>{body}")
            box.add_class("cadetgui-section")
            return box

        self.workflow = W.HTML(markdown_html(WORKFLOW_GUIDE))
        self.workflow.add_class("cadetgui-section")
        self.chain = section("Steps of the chain", _chain_html())
        self.lab_checks = section(
            "Lab checks the software cannot do",
            "<p>Check these yourself before fitting a step.</p>" + _lab_checks_html(),
        )
        self.optimizers = section(
            "Optimizers",
            "<p>Nelder-Mead minimizes a single objective. Each selected measurement is its own "
            "objective, so a step with other than exactly one measurement needs the "
            "multi-objective U-NSGA-III.</p>",
        )
        self.experiment_types = section("Experiment types", _experiment_types_html())
        self.glossary = section("Glossary", _glossary_html())
        self.root = W.VBox([
            W.HTML(style_tag()),
            W.HTML("<div class='cadetgui-panel-title'>Guide</div>"),
            self.workflow,
            self.chain,
            self.lab_checks,
            self.optimizers,
            self.experiment_types,
            self.glossary,
        ])
        self.root.add_class("cadetgui-panel")

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
