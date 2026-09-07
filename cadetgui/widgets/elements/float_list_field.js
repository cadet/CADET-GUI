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
