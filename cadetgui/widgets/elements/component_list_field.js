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

  const counter = document.createElement("span");
  counter.className = "cadetgui-field-count";

  function currentNames() {
    return Array.from(rows.querySelectorAll("input")).map((i) => i.value);
  }

  function updateCounter() {
    const n = rows.children.length;
    counter.textContent = `${n} component${n === 1 ? "" : "s"}`;
  }

  function commit() {
    model.set("value", currentNames());
    model.save_changes();
    updateCounter();
  }

  function addRow(name) {
    const row = document.createElement("div");
    row.className = "cadetgui-field-list-row";

    const input = document.createElement("input");
    input.type = "text";
    input.value = name;
    input.addEventListener("change", commit);
    row.appendChild(input);

    const rm = document.createElement("button");
    rm.type = "button";
    rm.textContent = "−";
    rm.title = "Remove component";
    rm.addEventListener("click", () => {
      if (rows.children.length <= 1) return; // always keep at least one
      row.remove();
      commit();
    });
    row.appendChild(rm);

    rows.appendChild(row);
  }

  function syncFromModel() {
    rows.innerHTML = "";
    const names = model.get("value") || [];
    (names.length ? names : ["Component 1"]).forEach((n) => addRow(n));
    updateCounter();
  }

  const addBtn = document.createElement("button");
  addBtn.type = "button";
  addBtn.className = "cadetgui-field-list-add";
  addBtn.textContent = "+ Add component";
  addBtn.addEventListener("click", () => {
    addRow(`Component ${rows.children.length + 1}`);
    commit();
  });

  const controls = document.createElement("div");
  controls.className = "cadetgui-field-list-controls";
  controls.appendChild(addBtn);
  controls.appendChild(counter);
  body.appendChild(controls);
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
