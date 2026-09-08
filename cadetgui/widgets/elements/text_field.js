const UNIT_GLOSSARY = {
  MP: "mobile phase",
  SP: "stationary phase",
  IV: "interstitial volume",
};

// Body-appended, fixed-position tooltip: Jupyter output areas clip
// overflow, so a ::after here gets cut off. Colors hardcoded -- outside
// any .cadetgui-field-scoped stylesheet.
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

function renderUnit(container, raw) {
  container.replaceChildren();
  if (!raw) return;
  const re = /\^([0-9]+)|_([A-Za-z0-9]+)|\*/g;
  let last = 0;
  let m;
  while ((m = re.exec(raw)) !== null) {
    if (m.index > last) container.append(raw.slice(last, m.index));
    if (m[1] !== undefined) {
      const sup = document.createElement("sup");
      sup.textContent = m[1];
      container.appendChild(sup);
    } else if (m[2] !== undefined) {
      const sub = document.createElement("sub");
      sub.textContent = m[2];
      const gloss = UNIT_GLOSSARY[m[2]];
      if (gloss) {
        sub.dataset.tooltip = gloss;
        sub.addEventListener("mouseenter", () => showTooltip(sub, gloss));
        sub.addEventListener("mouseleave", hideTooltip);
      }
      container.appendChild(sub);
    } else {
      container.append("·");
    }
    last = re.lastIndex;
  }
  if (last < raw.length) container.append(raw.slice(last));
}

function render({ model, el }) {
  const wrap = document.createElement("label");
  wrap.className = "cadetgui-field";

  const labelEl = document.createElement("span");
  labelEl.className = "cadetgui-field-label";
  labelEl.textContent = model.get("label");
  wrap.appendChild(labelEl);

  const input = document.createElement("input");
  input.type = "text";
  input.className = "cadetgui-field-input";
  input.value = model.get("value");
  input.addEventListener("change", () => {
    model.set("value", input.value);
    model.save_changes();
  });
  wrap.appendChild(input);

  const unitEl = document.createElement("span");
  unitEl.className = "cadetgui-field-unit";
  const syncUnit = () => {
    const units = model.get("units");
    renderUnit(unitEl, units);
    unitEl.hidden = !units;
  };
  wrap.appendChild(unitEl);
  syncUnit();

  const err = document.createElement("span");
  err.className = "cadetgui-field-error";
  const syncError = () => {
    const msg = model.get("error");
    err.textContent = msg;
    err.hidden = !msg;
    input.setAttribute("aria-invalid", msg ? "true" : "false");
  };
  wrap.appendChild(err);
  syncError();

  model.on("change:value", () => { input.value = model.get("value"); });
  model.on("change:error", syncError);
  model.on("change:label", () => { labelEl.textContent = model.get("label"); });
  model.on("change:units", syncUnit);

  el.appendChild(wrap);
}

export default { render };
