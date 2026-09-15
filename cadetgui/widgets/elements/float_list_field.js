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
  labelEl.title = model.get("label");
  wrap.appendChild(labelEl);

  const body = document.createElement("div");
  body.className = "cadetgui-field-list-body";
  const rows = document.createElement("div");
  body.appendChild(rows);

  function isPinned() {
    return (model.get("component_names") || []).length > 0;
  }

  function currentValues() {
    return Array.from(rows.querySelectorAll("input")).map((i) => parseFloat(i.value) || 0);
  }

  function commit() {
    model.set("value", currentValues());
    model.save_changes();
  }

  function addRow(value, componentName, showName) {
    const row = document.createElement("div");
    row.className = "cadetgui-field-list-row";

    if (showName && componentName !== undefined) {
      const nameEl = document.createElement("span");
      nameEl.className = "cadetgui-field-component-name";
      nameEl.textContent = componentName;
      row.appendChild(nameEl);
    }

    const input = document.createElement("input");
    input.type = "number";
    input.step = "any";
    input.value = formatNumber(value);
    input.addEventListener("change", commit);
    row.appendChild(input);

    if (!isPinned()) {
      const rm = document.createElement("button");
      rm.type = "button";
      rm.textContent = "−";
      rm.addEventListener("click", () => {
        row.remove();
        commit();
      });
      row.appendChild(rm);
    }

    const unitEl = document.createElement("span");
    unitEl.className = "cadetgui-field-unit";
    renderUnit(unitEl, model.get("units"));
    unitEl.hidden = !model.get("units");
    row.appendChild(unitEl);

    rows.appendChild(row);
  }

  function syncFromModel() {
    rows.innerHTML = "";
    const names = model.get("component_names") || [];
    const values = model.get("value") || [];
    // Stack (label on top, rows indented below with a name to the left of
    // each input) only when there's more than one row -- a single row
    // stays a normal inline field, same alignment as everything else.
    const rowCount = names.length > 0 ? names.length : Math.max(values.length, 1);
    const stacked = rowCount > 1;
    wrap.classList.toggle("cadetgui-field-list-stacked", stacked);

    if (names.length > 0) {
      names.forEach((name, i) => addRow(values[i] ?? 0, name, stacked));
      return;
    }
    (values.length ? values : [0]).forEach((v) => addRow(v, undefined, stacked));
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

  const syncPinned = () => {
    addBtn.hidden = isPinned();
  };

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

  syncPinned();
  syncFromModel();
  syncError();

  model.on("change:value", syncFromModel);
  model.on("change:component_names", () => { syncPinned(); syncFromModel(); });
  model.on("change:error", syncError);
  model.on("change:label", () => {
    labelEl.textContent = model.get("label");
    labelEl.title = model.get("label");
  });
  model.on("change:units", syncUnits);

  el.appendChild(wrap);
}

export default { render };
