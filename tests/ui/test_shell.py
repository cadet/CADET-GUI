"""SidebarShell: panes, groups, set_panes, warnings; step helpers of the workbenches."""

from __future__ import annotations

import ipywidgets as W
import pytest
from cadetgui.widgets.ui.shell import (
    SidebarShell,
    collect_panes,
    resolve_step,
    system_pane_label,
    validate_steps,
)

WARN = "exclamation-triangle"


def _panes(*labels):
    return {label: W.HTML(label) for label in labels}


def _shown(panes):
    return [label for label, pane in panes.items() if pane.layout.display != "none"]


def _keys(shell):
    return [key for _, key in shell.nav.options]


@pytest.fixture
def flat():
    panes = _panes("A", "B")
    return SidebarShell(list(panes.items())), panes


@pytest.fixture
def grouped():
    panes = _panes("A", "G: x", "G: y", "B")
    return SidebarShell(list(panes.items()), groups={"G": ["G: x", "G: y"]}), panes


def test_shows_one_pane_at_a_time_via_nav_or_show(flat):
    shell, panes = flat
    shown = []
    shell.add_show_listener(shown.append)
    assert (_shown(panes), shell.current, shell.order) == (["A"], "A", ["A", "B"])

    shell.nav.index = 1
    assert _shown(panes) == ["B"]

    shell.show("A")
    assert (_shown(panes), shell.nav.value) == (["A"], "A")
    assert shown == ["B", "A"]
    with pytest.raises(KeyError):
        shell.show("Z")


@pytest.mark.parametrize(
    "panes, groups, match",
    [
        ([], None, "at least one"),
        ([("A", W.HTML()), ("A", W.HTML())], None, "unique"),
        ([("A", W.HTML())], {"A": ["A"]}, "clashes"),
        ([("A", W.HTML())], {"G": ["A"], "H": ["A"]}, "more than one group"),
    ],
)
def test_rejects_invalid_panes_and_groups(panes, groups, match):
    with pytest.raises(ValueError, match=match):
        SidebarShell(panes, groups=groups)


def test_group_header_expands_and_collapses_without_switching_panes(grouped):
    shell, panes = grouped
    assert _keys(shell) == ["A", "G", "B"]

    shell.nav.value = "G"
    assert _keys(shell) == ["A", "G", "G: x", "G: y", "B"]
    assert [label for label, _ in shell.nav.options][2:4] == ["x", "y"]
    assert (_shown(panes), shell.nav.value) == (["A"], "A")

    shell.nav.value = "G: y"
    assert _shown(panes) == ["G: y"]

    shell.nav.value = "G"
    assert _keys(shell) == ["A", "G", "B"]
    assert (_shown(panes), shell.nav.value) == (["G: y"], None)


def test_warnings_mark_steps_and_collapsed_groups(flat, grouped):
    shell, _ = flat
    shell.set_warning("B", "needs data")
    assert (shell.nav.icons, shell.nav.tooltips) == (("", WARN), ("", "needs data"))
    shell.set_warning("B", None)
    assert shell.nav.icons == ("", "")
    with pytest.raises(KeyError):
        shell.set_warning("Z", "nope")

    shell, _ = grouped
    shell.set_warning("G: y", "no data")
    assert shell.nav.icons == ("", WARN, "")
    assert "no data" in shell.nav.tooltips[1]
    shell.show("G: y")
    assert shell.nav.icons == ("", "", "", WARN, "")


def test_set_panes_replaces_panes_keeping_selection_and_warnings(flat):
    shell, panes = flat
    c = W.HTML("C")
    shell.show("B")
    shell.set_warning("A", "careful")

    shell.set_panes([("B", panes["B"]), ("A", panes["A"]), ("C", c)])
    assert (shell.order, shell.current) == (["B", "A", "C"], "B")
    assert shell.nav.tooltips == ("", "careful", "")
    assert {panes["A"], panes["B"], c} <= set(shell.body.children[1].children)

    shell.set_panes([("A", panes["A"]), ("G: C", c)], groups={"G": ["G: C"]}, show="G: C")
    assert (shell.current, c.layout.display, panes["A"].layout.display) == ("G: C", "", "none")
    assert shell.nav.tooltips == ("careful", "", "")

    shell.set_panes([("A", panes["A"])])
    assert shell.current == "A"


def test_step_helpers_resolve_include_lists():
    validate_steps(("A",), known=("A", "B"))
    with pytest.raises(ValueError, match="'C'"):
        validate_steps(("A", "C"), known=("A", "B"))

    given, built = object(), object()
    assert resolve_step("A", given, steps=("A",), factory=object) is given
    assert resolve_step("A", None, steps=("A",), factory=lambda: built) is built
    assert resolve_step("A", None, steps=("B",), factory=pytest.fail) is None
    with pytest.raises(ValueError):
        resolve_step("A", given, steps=("B",), factory=object)

    slots = {"A": given, "B": None, "C": built}
    assert collect_panes(("A", "B", "C", "D"), slots) == [("A", given), ("C", built)]
    assert system_pane_label("Column") == "System: Column"
