from __future__ import annotations
import pytest
import ipywidgets as W

from cadetgui.widgets.elements import (
    BaseWidget,
    TextField,
    FloatField,
    BoolField,
    Display,
    Popup,
    ConfigurationWidget,
)


def test_basewidget_is_abstract():
    with pytest.raises(TypeError):
        BaseWidget()  # type: ignore[call-arg]


class Demo(BaseWidget):
    def _build_body(self) -> W.Widget:
        return W.Label("body")


def test_basewidget_concrete_builds_container():
    w = Demo(title="DemoTitle")
    assert isinstance(w.root, W.VBox)
    assert len(w.root.children) == 3
    header, body, status = w.root.children
    assert isinstance(header, W.HTML)
    assert "DemoTitle" in header.value
    assert isinstance(body, W.Label)
    assert isinstance(status, W.HTML)
    assert "Ready." in status.value


def test_display_no_raise_if_ipython_available():
    ip = pytest.importorskip("IPython")
    w = Demo()
    w.display()  


def test_textfield_get_set():
    tf = TextField(label="Name", value="Alice")
    assert tf.get_value() == "Alice"
    tf.set_value(123)  # coerces to str
    assert tf.get_value() == "123"


def test_floatfield_get_set():
    ff = FloatField(label="K", value=1.5)
    assert ff.get_value() == pytest.approx(1.5)
    ff.set_value("2.75")
    assert ff.get_value() == pytest.approx(2.75)


def test_boolfield_get_set():
    bf = BoolField(label="Flag", value=False)
    assert bf.get_value() is False
    bf.set_value(1)
    assert bf.get_value() is True


def test_display_constructs_html():
    d = Display(html="<b>Hi</b>")
    assert isinstance(d.widget, W.HTML)
    assert "Hi" in d.widget.value


def test_popup_open_close():
    p = Popup(title="Info")
    assert isinstance(p.widget, W.Accordion)
    # closed by default
    assert p.widget.selected_index is None
    p.open()
    assert p.widget.selected_index == 0
    p.close()
    assert p.widget.selected_index is None


def test_configuration_widget_add_fields_and_values():
    cfg = ConfigurationWidget(title="Cfg")
    # add fields
    cfg.add_field("name", TextField(label="Name"))
    cfg.add_field("alpha", FloatField(label="Alpha", value=0.1))
    cfg.add_field("active", BoolField(label="Active"))
    # layout should contain form + actions
    assert len(cfg.root.children) == 3  # header, body, status
    body = cfg.root.children[1]
    assert isinstance(body, W.VBox)
    # inner VBox children: form_box and actions
    form_box, actions = body.children
    assert isinstance(form_box, W.VBox)
    assert isinstance(actions, W.HBox)
    # fields show up in form
    assert len(form_box.children) == 3

    # set/get values
    cfg.set_values({"name": "col1", "alpha": 0.42, "active": True})
    values = cfg.get_values()
    assert values["name"] == "col1"
    assert values["alpha"] == pytest.approx(0.42)
    assert values["active"] is True
