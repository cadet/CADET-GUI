import ipywidgets as W
from cadetgui.widgets import Widget
from cadetgui.widgets.ui import (
    CodeView,
    SettingsPopover,
    collapsible,
    note,
    panel,
    section,
    table_html,
)


class _Counter(Widget):
    def __init__(self) -> None:
        super().__init__()
        self.root = panel("Counter", W.HTML("0"))

    def bump(self) -> None:
        self._notify(1)


def test_widget_notifies_listeners_and_renders_its_root():
    counter = _Counter()
    seen = []
    counter.add_listener(seen.append)
    counter.bump()
    assert seen == [1]
    bundle = counter._repr_mimebundle_()
    assert "application/vnd.jupyter.widget-view+json" in bundle


def test_panel_carries_style_title_and_class():
    box = panel("A <b>title</b>", W.HTML("body"))
    assert "<style>" in box.children[0].value
    assert "A <b>title</b>" in box.children[1].value
    assert "cadetgui-panel" in box._dom_classes
    assert len(panel(None, W.HTML()).children) == 2


def test_section_adds_classes_and_optional_title():
    box = section([W.HTML("x")], "cadetgui-section-half", title_html="T")
    assert {"cadetgui-section", "cadetgui-section-half"} <= set(box._dom_classes)
    assert "T" in box.children[0].value


def test_note_collapsible_and_settings_start_hidden_or_closed():
    assert note("x", hidden=True).layout.display == "none"
    assert collapsible("Events", W.HTML()).selected_index is None
    assert collapsible("Events", W.HTML(), open=True).selected_index == 0
    settings = SettingsPopover(tooltip="t", children=[W.HTML()])
    assert settings.box.layout.display == "none"
    settings.button.click()
    assert settings.box.layout.display == ""


def test_code_view_shows_escaped_code_only_when_toggled():
    view = CodeView(lambda: "a < b")
    assert view._body.layout.display == "none"
    view.toggle.value = True
    assert "a &lt; b" in view._body.value


def test_table_html_renders_rows_or_the_empty_text():
    out = table_html(["A", "B"], [["1", "2"]])
    assert "<th>A</th>" in out and "<td>2</td>" in out
    assert table_html(["A"], [], empty_html="<em>none</em>") == "<em>none</em>"
