const UNIT_GLOSSARY = {
  MP: "mobile phase",
  SP: "stationary phase",
  IV: "interstitial volume",
};

// Body-appended and fixed-position: Jupyter output areas clip overflow, which
// would cut off a CSS ::after tooltip. Colors are hardcoded because the
// element sits outside every scoped stylesheet.
function tooltipColors() {
  const dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  return dark ? { bg: "#9ca3af", fg: "#1f2937" } : { bg: "#6b7280", fg: "#ffffff" };
}

function getTooltipEl() {
  let tip = document.getElementById("cadetgui-tooltip");
  if (tip) return tip;
  tip = document.createElement("div");
  tip.id = "cadetgui-tooltip";
  Object.assign(tip.style, {
    position: "fixed",
    padding: "6px 12px",
    borderRadius: "2px",
    fontFamily: "system-ui, -apple-system, sans-serif",
    fontSize: "15px",
    fontStyle: "normal",
    lineHeight: "1.4",
    whiteSpace: "nowrap",
    pointerEvents: "none",
    opacity: "0",
    transition: "opacity 0.1s ease 80ms",
    zIndex: "999999",
  });
  document.body.appendChild(tip);
  return tip;
}

function showTooltip(anchorEl, text) {
  const tip = getTooltipEl();
  const { bg, fg } = tooltipColors();
  tip.style.background = bg;
  tip.style.color = fg;
  tip.textContent = text;
  const r = anchorEl.getBoundingClientRect();
  tip.style.left = `${r.left + r.width / 2}px`;
  tip.style.top = `${r.bottom + 10}px`;
  tip.style.transform = "translateX(-50%)";
  requestAnimationFrame(() => { tip.style.opacity = "1"; });
}

function hideTooltip() {
  const tip = document.getElementById("cadetgui-tooltip");
  if (tip) tip.style.opacity = "0";
}

function appendUnitNodes(container, nodes) {
  for (const node of nodes) {
    if (node.text !== undefined) {
      container.append(node.text);
      continue;
    }
    const el = document.createElement(node.sup ? "sup" : "sub");
    appendUnitNodes(el, node.sup || node.sub);
    const gloss = node.sub && UNIT_GLOSSARY[el.textContent];
    if (gloss) {
      el.dataset.tooltip = gloss;
      el.addEventListener("mouseenter", () => showTooltip(el, gloss));
      el.addEventListener("mouseleave", hideTooltip);
    }
    container.appendChild(el);
  }
}

function renderUnit(container, raw) {
  container.replaceChildren();
  if (!raw) return;
  appendUnitNodes(container, parseUnit(raw));
}

function setUnit(el, units) {
  renderUnit(el, units);
  el.hidden = !units;
}

function unitSpan(units) {
  const el = document.createElement("span");
  el.className = "cadetgui-field-unit";
  setUnit(el, units);
  return el;
}

function fieldUnit(model) {
  const el = unitSpan(model.get("units"));
  model.on("change:units", () => setUnit(el, model.get("units")));
  return el;
}
