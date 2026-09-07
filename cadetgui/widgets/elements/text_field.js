function render({ model, el }) {
  const wrap = document.createElement("label");
  wrap.className = "cadetgui-field";

  const labelEl = document.createElement("span");
  labelEl.className = "cadetgui-field-label";
  labelEl.textContent = model.get("label");
  wrap.appendChild(labelEl);

  const input = document.createElement("input");
  input.type = "text";
  input.className = "cadetgui-field-input";
  input.value = model.get("value");
  input.addEventListener("change", () => {
    model.set("value", input.value);
    model.save_changes();
  });
  wrap.appendChild(input);

  const err = document.createElement("span");
  err.className = "cadetgui-field-error";
  const syncError = () => {
    const msg = model.get("error");
    err.textContent = msg;
    err.hidden = !msg;
    input.setAttribute("aria-invalid", msg ? "true" : "false");
  };
  wrap.appendChild(err);
  syncError();

  model.on("change:value", () => { input.value = model.get("value"); });
  model.on("change:error", syncError);
  model.on("change:label", () => { labelEl.textContent = model.get("label"); });

  el.appendChild(wrap);
}

export default { render };
