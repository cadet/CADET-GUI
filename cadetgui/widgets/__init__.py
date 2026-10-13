"""Composable widgets for CADET-GUI.

This subpackage provides:
- base: `Widget`, the base class of every composite widget
- ui: shared building blocks (theme, layout, HTML snippets, formatting, plots, shell)
- elements: atomic anywidget input controls
- forms: FormRenderer, rendering a ModelSpec into elements
- composite: task widgets assembled from elements + forms

At this level: the most common composite widgets, the kit for building a bench
(`SidebarShell`, `bench_root` and the step/pane helpers) and the HTML helpers
the built-in widgets use for status lines, glossary terms and info boxes.
"""
from ._help import term_html
from .base import Widget
from .composite import (
    ConfigurationWidget,
    ParameterEstimationWidget,
    RunHistoryWidget,
    RunRecord,
    SolutionWidget,
)
from .composite.bench import bench_root
from .ui.html import StatusKind, checklist_html, info_box_html, status_html
from .ui.shell import (
    SYSTEM_GROUP,
    SidebarShell,
    collect_panes,
    resolve_step,
    system_pane_label,
    validate_steps,
)
from .ui.theme import style_tag

__all__ = [
    "Widget",
    "ConfigurationWidget",
    "SolutionWidget",
    "RunHistoryWidget",
    "RunRecord",
    "ParameterEstimationWidget",
    "SidebarShell",
    "bench_root",
    "SYSTEM_GROUP",
    "system_pane_label",
    "resolve_step",
    "validate_steps",
    "collect_panes",
    "StatusKind",
    "status_html",
    "term_html",
    "info_box_html",
    "checklist_html",
    "style_tag",
]
