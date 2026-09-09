function render({ model, el }) {
  const wrap = document.createElement("label");
  wrap.className = "cadetgui-field";

  const labelEl = document.createElement("span");
  labelEl.className = "cadetgui-field-label";
  labelEl.textContent = model.get("label");
  labelEl.title = model.get("label");
  wrap.appendChild(labelEl);

  const select = document.createElement("select");
  select.className = "cadetgui-field-select";

  function syncSelection() {
    const idx = model.get("selected_index");
    select.value = idx === null || idx === undefined ? "" : String(idx);
  }

  function syncOptions() {
    const labels = model.get("option_labels") || [];
    select.innerHTML = "";
    labels.forEach((text, i) => {
      const opt = document.createElement("option");
      opt.value = String(i);
      opt.textContent = text;
      select.appendChild(opt);
    });
    syncSelection();
  }

  select.addEventListener("change", () => {
    model.set("selected_index", select.value === "" ? null : parseInt(select.value, 10));
    model.save_changes();
  });
  wrap.appendChild(select);

  const err = document.createElement("span");
  err.className = "cadetgui-field-error";
  const syncError = () => {
    const msg = model.get("error");
    err.textContent = msg;
    err.hidden = !msg;
  };
  wrap.appendChild(err);

  syncOptions();
  syncError();

  model.on("change:option_labels", syncOptions);
  model.on("change:selected_index", syncSelection);
  model.on("change:error", syncError);
  model.on("change:label", () => {
    labelEl.textContent = model.get("label");
    labelEl.title = model.get("label");
  });

  el.appendChild(wrap);
}

export default { render };
