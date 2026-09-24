"""Unit strings are LaTeX source (no math delimiters) rendered by a small
hand-rolled parser duplicated in each element's JS. These tests pin the five
copies together and exercise the parser/DOM emitter in a headless browser."""
from __future__ import annotations

import re
from pathlib import Path

import cadetgui.widgets.elements as elements_pkg
import pytest
from cadetgui.parameters import _MODEL_CLASSES, get_parameters

ELEMENTS_DIR = Path(elements_pkg.__file__).parent
FORM_FIELDS = ["float_field", "float_list_field", "bool_field", "text_field"]
ALL_RENDERERS = FORM_FIELDS + ["line_chart"]

MP = '<sub data-tooltip="mobile phase">MP</sub>'
SP = '<sub data-tooltip="stationary phase">SP</sub>'
IV = '<sub data-tooltip="interstitial volume">IV</sub>'

RENDER_CASES = [
    (r"\mathrm{m}", "m"),
    (r"\mathrm{m}^{3}", "m<sup>3</sup>"),
    (r"m^3", "m<sup>3</sup>"),
    (r"\mathrm{m}^{-1}", "m<sup>-1</sup>"),
    (r"\frac{1}{\mathrm{s}}", "1/s"),
    (r"\frac{\mathrm{m}^{3}}{\mathrm{s}}", "m<sup>3</sup>/s"),
    (r"\frac{\mathrm{m}^{2}_{\mathrm{IV}}}{\mathrm{s}}", f"m<sup>2</sup>{IV}/s"),
    (
        r"\frac{\mathrm{mol}}{\mathrm{m}^{3}_{\mathrm{IV}}}",
        f"mol/m<sup>3</sup>{IV}",
    ),
    (
        r"\frac{\mathrm{m}^{3}_{\mathrm{MP}}}{\mathrm{m}^{3}_{\mathrm{SP}}\cdot\mathrm{s}}",
        f"m<sup>3</sup>{MP}/(m<sup>3</sup>{SP}·s)",
    ),
    (
        r"\frac{\mathrm{m}^{3}_{\mathrm{MP}}}{\mathrm{mol}\cdot\mathrm{s}}",
        f"m<sup>3</sup>{MP}/(mol·s)",
    ),
    (r"\mathrm{mol}\cdot\mathrm{s}", "mol·s"),
    (r"\mathrm{m}_{\mathrm{XY}}", "m<sub>XY</sub>"),
    (r"\frac{a}{b\cdot c}", "a/(b·c)"),
    (r"\frac{a\cdot b}{c}", "a·b/c"),
    (r"\frac{\frac{a}{b}}{c}", "(a/b)/c"),
    (r"\frac{a}{\frac{b}{c}}", "a/(b/c)"),
    (r"\mathrm{m}^{\mathrm{ab}}", "m<sup>ab</sup>"),
    (r"\unknown", "\\unknown"),
    ("", ""),
]


def test_unit_parser_is_identical_in_every_renderer():
    def parser_source(name):
        src = (ELEMENTS_DIR / f"{name}.js").read_text()
        match = re.search(r"^function parseUnit\(.*?^}\n", src, re.S | re.M)
        assert match, name
        return match.group(0)

    reference = parser_source(ALL_RENDERERS[0])
    for name in ALL_RENDERERS[1:]:
        assert parser_source(name) == reference, name


def test_unit_glossary_and_tooltip_are_identical_in_every_form_field():
    def chunk(name):
        src = (ELEMENTS_DIR / f"{name}.js").read_text()
        return src[: src.index("function parseUnit")]

    reference = chunk(FORM_FIELDS[0])
    assert "MP" in reference and "data-tooltip" not in reference
    for name in FORM_FIELDS[1:]:
        assert chunk(name) == reference, name


def test_form_fields_no_longer_tokenize_the_old_ad_hoc_notation():
    for name in ALL_RENDERERS:
        src = (ELEMENTS_DIR / f"{name}.js").read_text()
        assert r"\^([0-9]+)" not in src, name


@pytest.fixture(scope="module")
def browser_page():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # browser binary not installed
            pytest.skip(f"chromium unavailable: {exc}")
        page = browser.new_page()
        page.set_content("<html><body></body></html>")
        src = (ELEMENTS_DIR / "float_field.js").read_text()
        head = src[: src.index("function formatNumber")]
        page.add_script_tag(content=head)
        svg_src = (ELEMENTS_DIR / "line_chart.js").read_text()
        svg_head = svg_src[
            svg_src.index("function appendUnitNodesSvg") : svg_src.index("function formatTick")
        ]
        page.add_script_tag(
            content='const SVG_NS = "http://www.w3.org/2000/svg";\n' + svg_head
        )
        yield page
        browser.close()


RENDER_JS = """(raw) => {
  const el = document.createElement("span");
  renderUnit(el, raw);
  return el.innerHTML;
}"""


@pytest.mark.parametrize("raw, expected", RENDER_CASES)
def test_render_unit_produces_real_sup_sub_dom(browser_page, raw, expected):
    assert browser_page.evaluate(RENDER_JS, raw) == expected


def test_render_unit_wires_the_fast_custom_tooltip_on_phase_subscripts(browser_page):
    shown = browser_page.evaluate(
        """() => {
          const el = document.createElement("span");
          document.body.appendChild(el);
          renderUnit(el, String.raw`\\frac{\\mathrm{mol}}{\\mathrm{m}^{3}_{\\mathrm{SP}}}`);
          const sub = el.querySelector("sub");
          sub.dispatchEvent(new MouseEvent("mouseenter"));
          const tip = document.getElementById("cadetgui-tooltip");
          const text = tip.textContent;
          sub.dispatchEvent(new MouseEvent("mouseleave"));
          return { text, title: sub.getAttribute("title"), data: sub.dataset.tooltip };
        }"""
    )
    assert shown == {"text": "stationary phase", "title": None, "data": "stationary phase"}


def test_render_unit_does_not_tooltip_non_glossary_subscripts(browser_page):
    tooltipped = browser_page.evaluate(
        """() => {
          const el = document.createElement("span");
          renderUnit(el, String.raw`\\mathrm{m}_{\\mathrm{XY}}`);
          return el.querySelector("sub").hasAttribute("data-tooltip");
        }"""
    )
    assert tooltipped is False


def test_render_unit_replaces_previous_content(browser_page):
    html = browser_page.evaluate(
        """() => {
          const el = document.createElement("span");
          renderUnit(el, String.raw`\\mathrm{m}^{3}`);
          renderUnit(el, String.raw`\\mathrm{s}`);
          return el.innerHTML;
        }"""
    )
    assert html == "s"


def test_svg_unit_renderer_emits_baseline_shifted_tspans(browser_page):
    out = browser_page.evaluate(
        """() => {
          const t = document.createElementNS(SVG_NS, "text");
          renderUnitSvg(t, String.raw`\\frac{\\mathrm{m}^{3}_{\\mathrm{MP}}}{\\mathrm{s}}`);
          const label = (n) => `${n.getAttribute("baseline-shift")}:${n.textContent}`;
          return Array.from(t.childNodes).map((n) => (n.nodeType === 3 ? n.textContent : label(n)));
        }"""
    )
    assert out == ["m", "super:3", "sub:MP", "/s"]


def _live_units():
    units = set()
    for category, model in _MODEL_CLASSES:
        for meta in get_parameters(category, model).values():
            if meta.get("unit"):
                units.add(meta["unit"])
    return sorted(units)


def test_live_cadet_process_units_are_present_and_latex():
    units = _live_units()
    assert units
    assert not any("$" in u for u in units)


def test_every_live_cadet_process_unit_renders_without_leftover_latex(browser_page):
    for unit in _live_units():
        html = browser_page.evaluate(RENDER_JS, unit)
        text = re.sub(r"<[^>]+>", "", html)
        assert not any(ch in text for ch in "\\{}^_"), (unit, html)
