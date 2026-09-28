function render({ model, el }) {
  const wrap = document.createElement("label");
  wrap.className = "cadetgui-field";
  wrap.appendChild(fieldLabel(model));

  const select = document.createElement("select");
  select.className = "cadetgui-field-select";

  function syncSelection() {
    const idx = model.get("selected_index");
    select.value = idx == null ? "" : String(idx);
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
  wrap.appendChild(fieldError(model));

  syncOptions();
  model.on("change:option_labels", syncOptions);
  model.on("change:selected_index", syncSelection);
  bindDisabled(model, wrap);

  el.appendChild(wrap);
}

export default { render };
