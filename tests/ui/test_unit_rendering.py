"""Unit strings (CADET-Process's LaTeX subset) render the same in JS and Python."""

from __future__ import annotations

import re

import pytest
from cadetgui.parameters import get_parameters
from cadetgui.parameters.metadata import _MODEL_CLASSES
from cadetgui.widgets.ui import unit_html

CASES = [
    (r"\mathrm{m}", "m"),
    (r"m^3", "m<sup>3</sup>"),
    (r"\mathrm{m}^{-1}", "m<sup>-1</sup>"),
    (r"\frac{\mathrm{m}^{3}}{\mathrm{s}}", "m<sup>3</sup>/s"),
    (r"\frac{\mathrm{mol}}{\mathrm{m}^{3}_{\mathrm{IV}}}", "mol/m<sup>3</sup><sub>IV</sub>"),
    (
        r"\frac{\mathrm{m}^{3}_{\mathrm{MP}}}{\mathrm{m}^{3}_{\mathrm{SP}}\cdot\mathrm{s}}",
        "m<sup>3</sup><sub>MP</sub>/(m<sup>3</sup><sub>SP</sub>·s)",
    ),
    (r"\frac{a}{b\cdot c}", "a/(b·c)"),
    (r"\frac{a\cdot b}{c}", "a·b/c"),
    (r"\frac{\frac{a}{b}}{c}", "(a/b)/c"),
    (r"\frac{a}{\frac{b}{c}}", "a/(b/c)"),
    (r"\mathrm{m}^{\mathrm{ab}}", "m<sup>ab</sup>"),
    (r"\unknown", "\\unknown"),
    (r"\%", "%"),
    ("", ""),
]

HTML_JS = """(raw) => {
  const el = document.createElement("span");
  renderUnit(el, raw);
  return el.innerHTML.replace(/ data-tooltip="[^"]*"/g, "");
}"""

SVG_TEXT_JS = """(raw) => {
  const t = document.createElementNS(SVG_NS, "text");
  renderUnitSvg(t, raw);
  return t.textContent;
}"""


def _text(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def _live_units():
    units = set()
    for category, model in _MODEL_CLASSES:
        units.update(m["unit"] for m in get_parameters(category, model).values() if m.get("unit"))
    return sorted(units)


@pytest.mark.parametrize("raw, expected", CASES)
def test_python_renders_the_latex_subset(raw, expected):
    assert unit_html(raw) == expected


@pytest.mark.parametrize("raw, expected", CASES)
def test_js_html_and_svg_renderers_match_python(page, raw, expected):
    assert page.evaluate(HTML_JS, raw) == expected
    assert page.evaluate(SVG_TEXT_JS, raw) == _text(expected)


def test_live_cadet_process_units_render_identically_without_leftover_latex(
    page, cadet_process_descriptor_metadata
):
    units = _live_units()
    assert units and not any("$" in u for u in units)
    for unit in units:
        html = unit_html(unit)
        assert page.evaluate(HTML_JS, unit) == html, unit
        assert not any(ch in _text(html) for ch in "\\{}^_"), unit


def test_phase_subscripts_carry_a_glossary_tooltip(page):
    shown = page.evaluate(
        """(raw) => {
          const el = document.createElement("span");
          document.body.appendChild(el);
          renderUnit(el, raw);
          const [sp, xy] = el.querySelectorAll("sub");
          sp.dispatchEvent(new MouseEvent("mouseenter"));
          return [document.getElementById("cadetgui-tooltip").textContent,
                  xy.hasAttribute("data-tooltip")];
        }""",
        r"\frac{\mathrm{mol}}{\mathrm{m}^{3}_{\mathrm{SP}}\mathrm{m}_{XY}}",
    )
    assert shown == ["stationary phase", False]
