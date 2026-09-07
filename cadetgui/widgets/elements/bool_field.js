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

  el.appendChild(wrap);
}

export default { render };
