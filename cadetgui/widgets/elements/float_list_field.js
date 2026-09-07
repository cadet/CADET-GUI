const UNIT_GLOSSARY = {
  MP: "mobile phase",
  SP: "stationary phase",
  IV: "interstitial volume",
};

// Body-appended, position:fixed tooltip: Jupyter output-area containers
// clip overflow, so a ::after on the <sub> gets cut off near boundaries.
// Colors are hardcoded (not var(--cg-*)) since this lives outside any
// .cadetgui-field-scoped stylesheet.
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

function formatNumber(n) {
  if (!Number.isFinite(n) || n === 0) return String(n);
  const abs = Math.abs(n);
  if (abs < 1e-3 || abs >= 1e6) return n.toExponential();
  return String(n);
}

function render({ model, el }) {
  const wrap = document.createElement("div");
  wrap.className = "cadetgui-field cadetgui-field-list";

  const labelEl = document.createElement("span");
  labelEl.className = "cadetgui-field-label";
  labelEl.textContent = model.get("label");
  wrap.appendChild(labelEl);

  const body = document.createElement("div");
  body.className = "cadetgui-field-list-body";
  const rows = document.createElement("div");
  body.appendChild(rows);

  function currentValues() {
    return Array.from(rows.querySelectorAll("input")).map((i) => parseFloat(i.value) || 0);
  }

  function commit() {
    model.set("value", currentValues());
    model.save_changes();
  }

  function addRow(value) {
    const row = document.createElement("div");
    row.className = "cadetgui-field-list-row";

    const input = document.createElement("input");
    input.type = "number";
    input.step = "any";
    input.value = formatNumber(value);
    input.addEventListener("change", commit);
    row.appendChild(input);

    const rm = document.createElement("button");
    rm.type = "button";
    rm.textContent = "−";
    rm.addEventListener("click", () => {
      row.remove();
      commit();
    });
    row.appendChild(rm);

    const unitEl = document.createElement("span");
    unitEl.className = "cadetgui-field-unit";
    renderUnit(unitEl, model.get("units"));
    unitEl.hidden = !model.get("units");
    row.appendChild(unitEl);

    rows.appendChild(row);
  }

  function syncFromModel() {
    rows.innerHTML = "";
    const values = model.get("value") || [];
    (values.length ? values : [0]).forEach((v) => addRow(v));
  }

  const addBtn = document.createElement("button");
  addBtn.type = "button";
  addBtn.className = "cadetgui-field-list-add";
  addBtn.textContent = "+ add value";
  addBtn.addEventListener("click", () => {
    addRow(0);
    commit();
  });
  body.appendChild(addBtn);
  wrap.appendChild(body);

  const syncUnits = () => {
    const units = model.get("units");
    rows.querySelectorAll(".cadetgui-field-unit").forEach((unitEl) => {
      renderUnit(unitEl, units);
      unitEl.hidden = !units;
    });
  };

  const err = document.createElement("span");
  err.className = "cadetgui-field-error";
  const syncError = () => {
    const msg = model.get("error");
    err.textContent = msg;
    err.hidden = !msg;
  };
  wrap.appendChild(err);

  syncFromModel();
  syncError();

  model.on("change:value", syncFromModel);
  model.on("change:error", syncError);
  model.on("change:label", () => { labelEl.textContent = model.get("label"); });
  model.on("change:units", syncUnits);

  el.appendChild(wrap);
}

export default { render };
