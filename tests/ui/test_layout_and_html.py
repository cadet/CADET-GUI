"""Shared ui helpers: layout boxes, code view, HTML snippets, number formatting."""

from __future__ import annotations

import ipywidgets as W
import pytest
from cadetgui.widgets.ui import (
    CodeView,
    SettingsPopover,
    checklist_html,
    collapsible,
    info_box_html,
    logo_data_uri,
    note,
    panel,
    row,
    section,
    status_html,
    table_html,
    titled_header,
    toggle_box,
)
from cadetgui.widgets.ui.format import number_html
from cadetgui.widgets.ui.theme import style_tag


def test_layout_boxes_wrap_their_children():
    body = W.HTML("body")
    assert panel("Title", body).children[-1] is body
    assert len(panel(None, body).children) == 2
    assert section([body], title_html="T").children[-1] is body
    assert row(body).children == (body,)
    assert isinstance(titled_header("T", W.Button()).children[1], W.Button)
    assert logo_data_uri().startswith("data:image/png;base64,")


def test_hidden_and_closed_parts_open_on_demand():
    assert note("x", hidden=True).layout.display == "none"
    assert collapsible("Events", W.HTML()).selected_index is None
    assert collapsible("Events", W.HTML(), open=True).selected_index == 0

    box = W.VBox(layout=W.Layout(display="none"))
    assert toggle_box(box) is True and toggle_box(box) is False

    settings = SettingsPopover(tooltip="t", children=[W.HTML()])
    settings.button.click()
    assert settings.box.layout.display == ""
    settings.visible = False
    assert not settings.visible and settings.box.layout.display == "none"


def test_code_view_renders_escaped_code_only_when_toggled():
    calls = []
    view = CodeView(lambda: calls.append(1) or "a < b")
    assert calls == []

    view.toggle.value = True

    assert "a &lt; b" in view.root.children[1].value
    assert view.root.children[1].layout.display == ""


@pytest.mark.parametrize(
    "html",
    [
        status_html("error", "<b>"),
        status_html("running", "<b>"),
        info_box_html("<b>", "body"),
        checklist_html(["<b>"]),
    ],
)
def test_html_snippets_escape_plain_text(html):
    assert "&lt;b&gt;" in html and "<b>" not in html


def test_table_html_renders_rows_or_the_empty_text():
    out = table_html(["A", "B"], [["1", "2"]])
    assert "<th>A</th>" in out and "<td>2</td>" in out
    assert table_html(["A"], [], empty_html="<em>none</em>") == "<em>none</em>"


@pytest.mark.parametrize(
    "value, expected",
    [
        (0, "0"),
        (12.5, "12.5"),
        (1e-6, "10<sup>−6</sup>"),
        (2.5e5, "2.5 × 10<sup>5</sup>"),
        (True, "True"),
        ("<x>", "&lt;x&gt;"),
    ],
)
def test_number_html_switches_to_powers_of_ten_outside_a_moderate_range(value, expected):
    assert number_html(value) == expected


@pytest.mark.parametrize(
    "body, expected",
    [
        ("<body>", "dark"),
        ('<body data-jp-theme-light="true">', "light"),
        ('<body data-jp-theme-light="false">', "dark"),
        ('<body class="vscode-light">', "light"),
        ('<body class="vscode-dark">', "dark"),
    ],
    ids=["os-fallback", "jupyter-light", "jupyter-dark", "vscode-light", "vscode-dark"],
)
def test_theme_follows_the_notebook_host_before_the_os(chromium, body, expected):
    page = chromium.new_page(color_scheme="dark")
    page.set_content(f"<html>{body}{style_tag()}<div class='cadetgui-panel'></div></body></html>")
    theme = page.evaluate(
        "getComputedStyle(document.querySelector('.cadetgui-panel'))"
        ".getPropertyValue('--cg-theme').trim()"
    )
    page.close()
    assert theme == expected
