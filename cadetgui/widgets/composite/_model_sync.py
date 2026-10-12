"""Keep widgets that show parts of one model in step.

All objects of a CADET-Process model share one ComponentSystem; widgets register under it
and are refreshed when another widget edits the model.
"""

from __future__ import annotations

import weakref
from typing import Any, Optional

_watchers: "weakref.WeakKeyDictionary[Any, weakref.WeakSet]" = weakref.WeakKeyDictionary()


def watch(component_system: Any, widget: Any) -> None:
    """Call `widget.refresh()` whenever another widget edits this model."""
    _watchers.setdefault(component_system, weakref.WeakSet()).add(widget)


def changed(component_system: Any, source: Optional[Any] = None) -> None:
    """Refresh all widgets of this model except `source`."""
    for widget in list(_watchers.get(component_system, ())):
        if widget is source:
            continue
        try:
            widget.refresh()
        except Exception:  # noqa: BLE001
            pass
