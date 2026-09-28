from __future__ import annotations

import ipywidgets as W

from ...backend_versions import cadet_core_version, cadet_process_version
from .._chrome import style_tag

__all__ = ["BackendVersionsWidget", "backend_versions_text"]


def backend_versions_text() -> str:
    """One-line summary of the installed CADET-Process and CADET-Core versions."""
    process = cadet_process_version() or "not found"
    core = cadet_core_version() or "not found"
    return f"CADET-Process {process} · CADET-Core {core}"


class BackendVersionsWidget:
    """Compact read-only line showing the backend versions the GUI runs against."""

    def __init__(self) -> None:
        self._label = W.HTML(f"<span>{backend_versions_text()}</span>")
        self._label.add_class("cadetgui-backend-versions")
        self.root = W.VBox([W.HTML(style_tag()), self._label])
