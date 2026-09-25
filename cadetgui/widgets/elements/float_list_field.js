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

// Parses the LaTeX subset units are written in (^ _ {} \mathrm \cdot \frac)
// into [{ text } | { sup: nodes } | { sub: nodes }]. \frac is flattened to
// "a/b", with the denominator parenthesised when compound, so a unit stays
// on one line.
function parseUnit(src) {
  const symbols = { cdot: "·", times: "×", ",": " ", " ": " " };
  const textCommands = ["mathrm", "text", "textrm"];
  let i = 0;

  const append = (out, nodes) => {
    for (const node of nodes) {
      const last = out[out.length - 1];
      if (node.text !== undefined && last && last.text !== undefined) last.text += node.text;
      else out.push(node);
    }
  };
  const hasTopLevel = (nodes, chars) =>
    nodes.some((n) => n.text !== undefined && [...chars].some((c) => n.text.includes(c)));
  const paren = (nodes, needed) =>
    needed ? [{ text: "(" }, ...nodes, { text: ")" }] : nodes;

  function parseArg() {
    while (src[i] === " ") i++;
    if (i >= src.length) return [];
    if (src[i] === "{") {
      i++;
      return parseSeq(true);
    }
    const out = [];
    if (src[i] === "\\") {
      parseCommand(out);
    } else {
      append(out, [{ text: src[i] }]);
      i++;
    }
    return out;
  }

  function parseCommand(out) {
    i++;
    const letters = /^[A-Za-z]+/.exec(src.slice(i));
    const name = letters ? letters[0] : src.charAt(i);
    i += name.length;
    if (letters) while (src[i] === " ") i++;
    if (textCommands.includes(name)) {
      append(out, parseArg());
    } else if (name === "frac") {
      const num = parseArg();
      const den = parseArg();
      append(out, paren(num, hasTopLevel(num, "/")));
      append(out, [{ text: "/" }]);
      append(out, paren(den, hasTopLevel(den, "·×/")));
    } else if (name in symbols) {
      append(out, [{ text: symbols[name] }]);
    } else {
      append(out, [{ text: letters ? `\\${name}` : name || "\\" }]);
    }
  }

  function parseSeq(untilBrace) {
    const out = [];
    while (i < src.length) {
      const ch = src[i];
      if (ch === "}" && untilBrace) {
        i++;
        return out;
      }
      if (ch === "{") {
        i++;
        append(out, parseSeq(true));
      } else if (ch === "\\") {
        parseCommand(out);
      } else if (ch === "^" || ch === "_") {
        i++;
        out.push(ch === "^" ? { sup: parseArg() } : { sub: parseArg() });
      } else {
        append(out, [{ text: ch }]);
        i++;
      }
    }
    return out;
  }

  return parseSeq(false);
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

  model.on("change:value", () => { syncFromModel(); syncDisabled(); });
  model.on("change:component_names", () => { syncPinned(); syncFromModel(); syncDisabled(); });
  model.on("change:error", syncError);
  model.on("change:label", () => {
    labelEl.textContent = model.get("label");
    labelEl.title = model.get("label");
  });
  model.on("change:units", syncUnits);

  const syncDisabled = () => {
    const off = Boolean(model.get("disabled"));
    wrap.classList.toggle("cadetgui-field-disabled", off);
    wrap.querySelectorAll("input, select, button").forEach((n) => { n.disabled = off; });
  };
  syncDisabled();
  model.on("change:disabled", syncDisabled);

  el.appendChild(wrap);
}

export default { render };
