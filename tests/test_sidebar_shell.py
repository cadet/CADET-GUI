from __future__ import annotations

import ipywidgets as W
import pytest
from cadetgui.widgets._sidebar_shell import (
    SidebarShell,
    collect_panes,
    resolve_step,
    validate_steps,
)


def _pane() -> W.Widget:
    return W.HTML("pane")


def test_sidebar_shell_shows_only_the_first_pane_initially():
    a, b = _pane(), _pane()
    shell = SidebarShell([("A", a), ("B", b)])

    assert a.layout.display == ""
    assert b.layout.display == "none"
    assert shell.nav.index == 0


def test_sidebar_shell_nav_click_switches_the_visible_pane():
    a, b = _pane(), _pane()
    shell = SidebarShell([("A", a), ("B", b)])

    shell.nav.index = 1

    assert a.layout.display == "none"
    assert b.layout.display == ""


def test_sidebar_shell_show_switches_the_visible_pane_and_the_nav():
    a, b = _pane(), _pane()
    shell = SidebarShell([("A", a), ("B", b)])

    shell.show("B")

    assert a.layout.display == "none"
    assert b.layout.display == ""
    assert shell.nav.value == "B"


def test_sidebar_shell_rejects_empty_panes():
    with pytest.raises(ValueError):
        SidebarShell([])


def test_sidebar_shell_rejects_duplicate_labels():
    with pytest.raises(ValueError):
        SidebarShell([("A", _pane()), ("A", _pane())])


def test_sidebar_shell_combines_arbitrary_widgets_not_just_composite_ones():
    """The whole point of the split: any (label, widget) pairs, not a fixed set."""
    picker = W.Dropdown(options=["x", "y"])
    plot_out = W.Output()

    shell = SidebarShell([("Pick", picker), ("Plot", plot_out)])

    assert picker.layout.display == ""
    assert plot_out.layout.display == "none"


def test_validate_steps_accepts_a_subset_of_known():
    validate_steps(("A",), known=("A", "B"))  # no raise


def test_validate_steps_rejects_anything_outside_known():
    with pytest.raises(ValueError):
        validate_steps(("A", "C"), known=("A", "B"))


def test_resolve_step_uses_the_given_widget_when_provided():
    widget = object()

    assert resolve_step("A", widget, steps=("A",), factory=object) is widget


def test_resolve_step_builds_a_default_when_included_and_nothing_given():
    sentinel = object()

    resolved = resolve_step("A", None, steps=("A", "B"), factory=lambda: sentinel)

    assert resolved is sentinel


def test_resolve_step_skips_construction_when_excluded():
    calls = []

    resolved = resolve_step("A", None, steps=("B",), factory=lambda: calls.append(1))

    assert resolved is None
    assert calls == []  # factory never ran


def test_resolve_step_rejects_a_given_widget_for_an_excluded_step():
    with pytest.raises(ValueError):
        resolve_step("A", object(), steps=("B",), factory=object)


def test_collect_panes_keeps_order_and_drops_none_slots():
    a, c = object(), object()

    panes = collect_panes(("A", "B", "C"), {"A": a, "B": None, "C": c})

    assert panes == [("A", a), ("C", c)]


def test_collect_panes_tolerates_a_slot_missing_from_the_map():
    panes = collect_panes(("A", "B"), {"A": "x"})

    assert panes == [("A", "x")]


def test_set_warning_marks_a_step_with_an_icon_and_tooltip_and_clears_it():
    shell = SidebarShell([("A", _pane()), ("B", _pane())])

    shell.set_warning("B", "needs data")

    assert shell.nav.icons == ("", "exclamation-triangle")
    assert shell.nav.tooltips == ("", "needs data")
    assert list(shell.nav.options) == ["A", "B"]  # navigation itself is untouched

    shell.set_warning("B", None)

    assert shell.nav.icons == ("", "")
    assert shell.nav.tooltips == ("", "")


def test_set_warning_rejects_an_unknown_step():
    shell = SidebarShell([("A", _pane())])

    with pytest.raises(KeyError):
        shell.set_warning("Z", "nope")


def _grouped():
    panes = {name: _pane() for name in ("A", "G: x", "G: y", "B")}
    shell = SidebarShell(list(panes.items()), groups={"G": ["G: x", "G: y"]})
    return shell, panes


def _keys(shell):
    return [key for _, key in shell.nav.options]


def test_group_collapses_children_under_one_header():
    shell, _ = _grouped()

    assert _keys(shell) == ["A", "G", "B"]


def test_clicking_a_group_header_expands_and_collapses_without_switching_panes():
    shell, panes = _grouped()

    shell.nav.value = "G"

    assert _keys(shell) == ["A", "G", "G: x", "G: y", "B"]
    assert [label for label, _ in shell.nav.options][2:4] == ["x", "y"]
    assert panes["A"].layout.display == ""
    assert shell.nav.value == "A"

    shell.nav.value = "G"

    assert _keys(shell) == ["A", "G", "B"]


def test_showing_a_child_expands_its_group_and_collapsed_group_stays_clickable():
    shell, panes = _grouped()

    shell.show("G: y")

    assert _keys(shell) == ["A", "G", "G: x", "G: y", "B"]
    assert shell.nav.value == "G: y"
    assert panes["G: y"].layout.display == ""

    shell.nav.value = "G"

    assert _keys(shell) == ["A", "G", "B"]
    assert shell.nav.value is None
    assert panes["G: y"].layout.display == ""

    shell.nav.value = "G"

    assert shell.nav.value == "G: y"


def test_selecting_a_child_via_nav_switches_pane():
    shell, panes = _grouped()
    shell.show("G: x")

    shell.nav.value = "G: y"

    assert panes["G: y"].layout.display == ""
    assert panes["G: x"].layout.display == "none"


def test_group_header_shows_a_child_warning_only_while_collapsed():
    shell, _ = _grouped()

    shell.set_warning("G: y", "no data")

    assert shell.nav.icons == ("", "exclamation-triangle", "")
    assert "no data" in shell.nav.tooltips[1]

    shell.show("G: y")

    assert shell.nav.icons == ("", "", "", "exclamation-triangle", "")


def test_group_validation():
    with pytest.raises(ValueError):
        SidebarShell([("A", _pane())], groups={"A": ["A"]})
    shell = SidebarShell([("A", _pane())], groups={"G": ["Z"]})
    assert list(shell.nav.options) == ["A"]
