"""Browser fixtures for the JS views of elements and unit strings."""

from __future__ import annotations

from pathlib import Path

import cadetgui.widgets.elements as elements_pkg
import pytest

ELEMENTS_DIR = Path(elements_pkg.__file__).parent

MOUNT_JS = """async ({ esm, state }) => {
  const url = URL.createObjectURL(new Blob([esm], { type: "text/javascript" }));
  const mod = await import(url);
  const listeners = {};
  const saved = [];
  const model = {
    get: (key) => state[key],
    set: (key, value) => { state[key] = value; },
    save_changes: () => saved.push({ ...state }),
    on: (event, cb) => { (listeners[event] = listeners[event] || []).push(cb); },
  };
  const el = document.createElement("div");
  document.body.replaceChildren(el);
  mod.default.render({ model, el });
  window.view = {
    el,
    saved,
    q: (sel) => el.querySelector(sel),
    qa: (sel) => Array.from(el.querySelectorAll(sel)),
    change: (name, value) => {
      state[name] = value;
      (listeners["change:" + name] || []).forEach((cb) => cb());
    },
  };
}"""


class View:
    """An element's JS view rendered against a fake anywidget model."""

    def __init__(self, page, widget):
        self.page = page
        state = {k: v for k, v in widget.get_state().items() if not k.startswith("_")}
        page.evaluate(MOUNT_JS, {"esm": widget._esm, "state": state})

    def js(self, body: str):
        return self.page.evaluate(f"() => {{ const v = window.view; {body} }}")

    def text(self, selector: str) -> str:
        return self.js(f"return v.q({selector!r}).textContent;")

    def last_saved(self) -> dict:
        return self.js("return v.saved[v.saved.length - 1];")


@pytest.fixture(scope="module")
def page(chromium):
    """A blank page with the unit parser, the HTML and the SVG unit renderers loaded."""
    page = chromium.new_page()
    page.set_content("<html><body></body></html>")
    for name in ("shared/unit_parser", "shared/unit_dom"):
        page.add_script_tag(content=(ELEMENTS_DIR / f"{name}.js").read_text())
    chart = (ELEMENTS_DIR / "line_chart.js").read_text()
    svg_renderer = chart[
        chart.index("function appendUnitNodesSvg") : chart.index("function formatTick")
    ]
    page.add_script_tag(content='const SVG_NS = "http://www.w3.org/2000/svg";\n' + svg_renderer)
    yield page
    page.close()


@pytest.fixture
def mount(page):
    """Render an element's view in the browser."""
    return lambda widget: View(page, widget)
