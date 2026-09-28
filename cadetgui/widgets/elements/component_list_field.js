function render({ model, el }) {
  const wrap = document.createElement("div");
  wrap.className = "cadetgui-field cadetgui-field-list";
  wrap.appendChild(fieldLabel(model));

  const body = document.createElement("div");
  body.className = "cadetgui-field-list-body";
  const rows = document.createElement("div");
  body.appendChild(rows);

  const counter = document.createElement("span");
  counter.className = "cadetgui-field-count";

  const minComponents = () => model.get("min_components") || 1;

  function updateCounter() {
    const n = rows.children.length;
    counter.textContent = `${n} component${n === 1 ? "" : "s"}`;
  }

  function updateRemoveButtons() {
    const atMin = rows.children.length <= minComponents();
    rows.querySelectorAll(".cadetgui-field-list-remove").forEach((btn) => {
      btn.disabled = atMin;
    });
  }

  function commit() {
    const names = Array.from(rows.querySelectorAll("input")).map((i) => i.value);
    model.set("value", names);
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
    rm.className = "cadetgui-field-list-remove";
    rm.textContent = "−";
    rm.title = "Remove component";
    rm.addEventListener("click", () => {
      if (rows.children.length <= minComponents()) return;
      row.remove();
      commit();
      updateRemoveButtons();
    });
    row.appendChild(rm);

    rows.appendChild(row);
  }

  function syncFromModel() {
    rows.innerHTML = "";
    const names = model.get("value") || [];
    const list = names.length ? names : ["Component 1"];
    list.forEach((n) => addRow(n));
    wrap.classList.toggle("cadetgui-field-list-stacked", list.length > 1);
    updateCounter();
    updateRemoveButtons();
  }

  const addBtn = document.createElement("button");
  addBtn.type = "button";
  addBtn.className = "cadetgui-field-list-add";
  addBtn.textContent = "+ Add component";
  addBtn.addEventListener("click", () => {
    addRow(`Component ${rows.children.length + 1}`);
    commit();
    updateRemoveButtons();
  });

  const controls = document.createElement("div");
  controls.className = "cadetgui-field-list-controls";
  controls.appendChild(addBtn);
  controls.appendChild(counter);
  body.appendChild(controls);
  wrap.appendChild(body);
  wrap.appendChild(fieldError(model));

  syncFromModel();
  model.on("change:value", syncFromModel);
  model.on("change:min_components", updateRemoveButtons);

  el.appendChild(wrap);
}

export default { render };
