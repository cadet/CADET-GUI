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
  wrap.appendChild(fieldLabel(model));
  wrap.appendChild(fieldUnit(model));
  wrap.appendChild(fieldError(model));

  model.on("change:value", () => { input.checked = Boolean(model.get("value")); });
  bindDisabled(model, wrap);

  el.appendChild(wrap);
}

export default { render };
