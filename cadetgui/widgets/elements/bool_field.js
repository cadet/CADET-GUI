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

function render({ model, el }) {
  const wrap = document.createElement("label");
  wrap.className = "cadetgui-field cadetgui-field-bool";

  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = Boolean(model.get("value"));
  input.addEventListener("change", () => {
    model.set("value", input.checked);
    model.save_changes();
  });
  wrap.appendChild(input);

  const labelEl = document.createElement("span");
  labelEl.className = "cadetgui-field-label";
  labelEl.textContent = model.get("label");
  labelEl.title = model.get("label");
  wrap.appendChild(labelEl);

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
  };
  wrap.appendChild(err);
  syncError();

  model.on("change:value", () => { input.checked = Boolean(model.get("value")); });
  model.on("change:error", syncError);
  model.on("change:label", () => {
    labelEl.textContent = model.get("label");
    labelEl.title = model.get("label");
  });
  model.on("change:units", syncUnit);

  el.appendChild(wrap);
}

export default { render };
