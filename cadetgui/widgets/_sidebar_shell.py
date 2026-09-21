from __future__ import annotations

from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple, TypeVar

import ipywidgets as W

__all__ = ["SidebarShell", "validate_steps", "resolve_step", "collect_panes"]

_T = TypeVar("_T")


class SidebarShell:
    """A left-sidebar nav that shows exactly one pane at a time.

    Generic over its panes: takes `(label, widget)` pairs and does only the
    nav/show-hide mechanics (single `ToggleButtons`, `layout.display`
    toggling -- state on a hidden pane survives switching away from it, same
    as `_settings_popover.toggle_box`). Wiring between panes
    (`bind_to_config`, `add_listener`, ...) is the caller's job before
    constructing this -- `WorkbenchWidget` is the reference example.
    """

    def __init__(self, panes: Sequence[Tuple[str, W.Widget]]) -> None:
        if not panes:
            raise ValueError("SidebarShell needs at least one pane")
        labels = [label for label, _ in panes]
        if len(set(labels)) != len(labels):
            raise ValueError(f"Pane labels must be unique, got {labels!r}")

        self._order: List[str] = labels
        self.panes: Dict[str, W.Widget] = dict(panes)
        for widget in self.panes.values():
            widget.layout.display = "none"

        self.nav = W.ToggleButtons(options=self._order)
        self.nav.add_class("cadetgui-sidebar-nav")
        self.nav.observe(self._on_nav_change, names="index")

        content = W.VBox(list(self.panes.values()))
        content.add_class("cadetgui-workbench-content")

        self.body = W.HBox([self.nav, content])
        self.body.add_class("cadetgui-workbench-body")

        self.show(self._order[0])

    def show(self, label: str) -> None:
        """Switch to the pane registered under `label`."""
        for name, widget in self.panes.items():
            widget.layout.display = "" if name == label else "none"
        if self.nav.value != label:
            self.nav.value = label

    def _on_nav_change(self, change: dict) -> None:
        if change.get("name") != "index":
            return
        self.show(self._order[change["new"]])

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.body)


def validate_steps(steps: Sequence[str], known: Sequence[str]) -> None:
    """Raise ValueError if `steps` contains anything outside `known`.

    For validating an `include=(...)` argument against the fixed set of
    steps a shell actually knows how to build -- see `resolve_step` for the
    per-step half of the same pattern.
    """
    unknown = set(steps) - set(known)
    if unknown:
        raise ValueError(
            f"Unknown step(s) {sorted(unknown)!r}, expected a subset of {tuple(known)!r}"
        )


def resolve_step(
    label: str,
    given: Optional[_T],
    *,
    steps: Sequence[str],
    factory: Callable[[], _T],
) -> Optional[_T]:
    """Resolve one optional, possibly-excluded pane's widget.

    The recurring shape behind any `WorkbenchWidget`-style "build me a
    sidebar over these steps, let the caller inject their own widget for
    any of them" composer:

    - `given` (an explicit pre-built widget, or None) always wins.
    - Otherwise, build a fresh default via `factory()` -- but only if
      `label` is actually in `steps`; an excluded step resolves to `None`
      rather than being built and then hidden, so skipping a step costs
      nothing (no widget constructed, nothing to wire listeners to).
    - Passing `given` for a `label` not in `steps` is a contradiction (you
      supplied a widget for a step you also said to skip) and raises,
      rather than silently building it anyway or silently dropping it.

    A shell with three optional steps calls this once per step:

        self.configuration = resolve_step(
            "Configuration", configuration, steps=steps, factory=ConfigurationWidget
        )
    """
    if given is not None and label not in steps:
        raise ValueError(f"{label!r} widget was given but not in include={tuple(steps)!r}")
    if given is not None:
        return given
    return factory() if label in steps else None


def collect_panes(order: Sequence[str], slots: Mapping[str, Optional[_T]]) -> List[Tuple[str, _T]]:
    """Build `SidebarShell`'s pane list from a `{label: widget-or-None}` map.

    Keeps `order`'s ordering; drops any label whose slot is `None` -- the
    "excluded via `include`" result `resolve_step` returns -- since
    `SidebarShell` requires every pane it's given to be a real widget.
    """
    return [(label, slots[label]) for label in order if slots.get(label) is not None]
