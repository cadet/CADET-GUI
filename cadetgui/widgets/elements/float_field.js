const UNIT_GLOSSARY = {
  MP: "mobile phase",
  SP: "stationary phase",
  IV: "interstitial volume",
};

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
      if (UNIT_GLOSSARY[m[2]]) sub.title = UNIT_GLOSSARY[m[2]];
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
  const wrap = document.createElement("label");
  wrap.className = "cadetgui-field";

  const labelEl = document.createElement("span");
  labelEl.className = "cadetgui-field-label";
  labelEl.textContent = model.get("label");
  wrap.appendChild(labelEl);

  const input = document.createElement("input");
  input.type = "number";
  input.step = "any";
  input.className = "cadetgui-field-input";

  const syncBounds = () => {
    const min = model.get("min");
    const max = model.get("max");
    if (min === null || min === undefined) input.removeAttribute("min");
    else input.min = String(min);
    if (max === null || max === undefined) input.removeAttribute("max");
    else input.max = String(max);
  };
  const syncValue = () => {
    input.value = formatNumber(model.get("value"));
  };
  const syncError = () => {
    const msg = model.get("error");
    err.textContent = msg;
    err.hidden = !msg;
    input.setAttribute("aria-invalid", msg ? "true" : "false");
  };

  syncBounds();
  syncValue();

  input.addEventListener("change", () => {
    const parsed = parseFloat(input.value);
    if (!Number.isNaN(parsed)) {
      model.set("value", parsed);
      model.save_changes();
    }
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
  wrap.appendChild(err);
  syncError();

  model.on("change:value", syncValue);
  model.on("change:min", syncBounds);
  model.on("change:max", syncBounds);
  model.on("change:error", syncError);
  model.on("change:label", () => { labelEl.textContent = model.get("label"); });
  model.on("change:units", syncUnit);

  el.appendChild(wrap);
}

export default { render };
