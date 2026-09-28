function render({ model, el }) {
  const wrap = document.createElement("div");
  wrap.className = "cadetgui-field cadetgui-field-list";
  wrap.appendChild(fieldLabel(model));

  const body = document.createElement("div");
  body.className = "cadetgui-field-list-body";
  const rows = document.createElement("div");
  body.appendChild(rows);

  const isPinned = () => (model.get("component_names") || []).length > 0;

  function commit() {
    const values = Array.from(rows.querySelectorAll("input")).map((i) => parseFloat(i.value) || 0);
    model.set("value", values);
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

    row.appendChild(unitSpan(model.get("units")));
    rows.appendChild(row);
  }

  function syncFromModel() {
    rows.innerHTML = "";
    const names = model.get("component_names") || [];
    const values = model.get("value") || [];
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
  wrap.appendChild(fieldError(model));

  const syncPinned = () => {
    addBtn.hidden = isPinned();
  };

  syncPinned();
  syncFromModel();
  const syncDisabled = bindDisabled(model, wrap);

  model.on("change:value", () => { syncFromModel(); syncDisabled(); });
  model.on("change:component_names", () => { syncPinned(); syncFromModel(); syncDisabled(); });
  model.on("change:units", () => {
    rows.querySelectorAll(".cadetgui-field-unit").forEach((unitEl) => {
      setUnit(unitEl, model.get("units"));
    });
  });

  el.appendChild(wrap);
}

export default { render };
