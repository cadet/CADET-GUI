from __future__ import annotations

import itertools
from typing import (
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    TypeVar,
)

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

    `groups` maps a group label to the pane labels nested under it. A group
    is one collapsible entry in the nav, placed where its first child sits;
    expanded, its children follow, indented and shown without a shared
    `"<group>: "` prefix. Without `groups`, `nav.options` is just the pane
    labels; with them it is `(display, key)` pairs and `nav.value` is the
    pane label, or `None` while the selected pane sits in a collapsed group.
    """

    _instances = itertools.count()

    def __init__(
        self,
        panes: Sequence[Tuple[str, W.Widget]],
        groups: Optional[Mapping[str, Sequence[str]]] = None,
    ) -> None:
        if not panes:
            raise ValueError("SidebarShell needs at least one pane")
        labels = [label for label, _ in panes]
        if len(set(labels)) != len(labels):
            raise ValueError(f"Pane labels must be unique, got {labels!r}")

        self._order: List[str] = labels
        self.panes: Dict[str, W.Widget] = dict(panes)
        self._groups: Dict[str, List[str]] = {}
        self._group_of: Dict[str, str] = {}
        for group, children in (groups or {}).items():
            if group in self.panes:
                raise ValueError(f"Group label {group!r} clashes with a pane label")
            present = [label for label in labels if label in children]
            for child in present:
                if child in self._group_of:
                    raise ValueError(f"Pane {child!r} is in more than one group")
                self._group_of[child] = group
            if present:
                self._groups[group] = present
        for widget in self.panes.values():
            widget.layout.display = "none"

        self._warnings: Dict[str, str] = {}
        self._expanded: Set[str] = set()
        self._current: str = self._order[0]
        self._entries: List[Tuple[str, str]] = []
        self._syncing = False

        self._nav_class = f"cadetgui-sidebar-nav-{next(self._instances)}"
        self.nav = W.ToggleButtons(options=self._order)
        self.nav.add_class("cadetgui-sidebar-nav")
        self.nav.add_class(self._nav_class)
        self.nav.observe(self._on_nav_change, names="index")
        self._nav_style = W.HTML()

        content = W.VBox([self._nav_style, *self.panes.values()])
        content.add_class("cadetgui-workbench-content")

        self.body = W.HBox([self.nav, content])
        self.body.add_class("cadetgui-workbench-body")

        self.show(self._order[0])

    def show(self, label: str) -> None:
        """Switch to the pane registered under `label`, expanding its group."""
        if label not in self.panes:
            raise KeyError(label)
        self._current = label
        if label in self._group_of:
            self._expanded.add(self._group_of[label])
        for name, widget in self.panes.items():
            widget.layout.display = "" if name == label else "none"
        self._sync_nav()

    def set_warning(self, label: str, message: Optional[str]) -> None:
        """Mark a step with a warning icon and hover text, or clear it with `None`.

        Purely informational -- the step stays selectable. A collapsed group
        shows the marker for any warned child.
        """
        if label not in self.panes:
            raise KeyError(label)
        if message:
            self._warnings[label] = message
        else:
            self._warnings.pop(label, None)
        self._sync_nav()

    def _visible_entries(self) -> List[Tuple[str, str]]:
        entries: List[Tuple[str, str]] = []
        seen: Set[str] = set()
        for label in self._order:
            group = self._group_of.get(label)
            if group is None:
                entries.append((label, label))
            elif group not in seen:
                seen.add(group)
                chevron = "\u25be" if group in self._expanded else "\u25b8"
                entries.append((f"{chevron} {group}", group))
                if group in self._expanded:
                    for child in self._groups[group]:
                        entries.append((self._child_label(group, child), child))
        return entries

    @staticmethod
    def _child_label(group: str, child: str) -> str:
        prefix = f"{group}: "
        return child[len(prefix):] if child.startswith(prefix) else child

    def _warning_for(self, key: str) -> str:
        if key in self._groups:
            if key in self._expanded:
                return ""
            return "\n".join(
                f"{child}: {self._warnings[child]}"
                for child in self._groups[key]
                if child in self._warnings
            )
        return self._warnings.get(key, "")

    def _sync_nav(self) -> None:
        entries = self._visible_entries()
        keys = [key for _, key in entries]
        collapsed_group = self._group_of.get(self._current)
        if collapsed_group is not None and collapsed_group in self._expanded:
            collapsed_group = None
        value = self._current if self._current in keys else None

        self._syncing = True
        try:
            if entries != self._entries:
                self._entries = entries
                if self._groups:
                    self.nav.options = entries
                else:
                    self.nav.options = keys
            if self.nav.value != value:
                self.nav.value = value
            warnings = [self._warning_for(key) for key in keys]
            self.nav.icons = tuple("exclamation-triangle" if w else "" for w in warnings)
            self.nav.tooltips = tuple(warnings)
        finally:
            self._syncing = False
        self._nav_style.value = self._style_for(entries, collapsed_group)

    def _style_for(self, entries: List[Tuple[str, str]], active_group: Optional[str]) -> str:
        rules = []
        for position, (_, key) in enumerate(entries, start=1):
            target = f".{self._nav_class} .widget-toggle-button:nth-child({position})"
            if key in self._group_of:
                rules.append(f"{target}{{padding-left:calc(var(--cg-space-3) + 16px)}}")
            elif key == active_group:
                rules.append(
                    f"{target}{{background:color-mix(in srgb, var(--cg-focus) 12%, transparent);"
                    "box-shadow:inset 3px 0 0 var(--cg-focus);color:var(--cg-focus);"
                    "font-weight:600}"
                )
        return f"<style>{''.join(rules)}</style>" if rules else ""

    def _on_nav_change(self, change: dict) -> None:
        if self._syncing or change.get("name") != "index":
            return
        key = self.nav.value
        if key is None:
            return
        if key in self._groups:
            if key in self._expanded:
                self._expanded.discard(key)
            else:
                self._expanded.add(key)
            self._sync_nav()
            return
        self.show(key)

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
            "Process Configuration", configuration, steps=steps, factory=ConfigurationWidget
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
