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
    input.value = value;
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

  el.appendChild(wrap);
}

export default { render };
