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
  model.on("change:label", () => { labelEl.textContent = model.get("label"); });
  model.on("change:units", syncUnit);

  el.appendChild(wrap);
}

export default { render };
