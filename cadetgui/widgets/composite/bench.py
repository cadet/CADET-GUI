from __future__ import annotations

from typing import Any, Optional

import ipywidgets as W

from .._chrome import logo_data_uri, style_tag
from ..shell import SidebarShell
from .workspace_header import hoisted_header_rows

__all__ = ["bench_root"]


def bench_root(title: str, shell: SidebarShell, configuration: Optional[Any] = None) -> W.VBox:
    """Frame `shell` as a workbench: top bar with `title`, the configuration's header, panes."""
    top_bar = W.HTML(
        "<div class='cadetgui-topbar'>"
        f"<img src='{logo_data_uri()}' alt='CADET'>"
        f"<span class='cadetgui-topbar-title'>{title}</span>"
        "</div>"
    )
    root = W.VBox([
        W.HTML(style_tag()), top_bar, *hoisted_header_rows(configuration), shell.body
    ])
    root.add_class("cadetgui-panel")
    root.add_class("cadetgui-workbench")
    return root
