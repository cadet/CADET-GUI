function render({ model, el }) {
  const wrap = document.createElement("label");
  wrap.className = "cadetgui-field";
  wrap.appendChild(fieldLabel(model));

  const input = document.createElement("input");
  input.type = "text";
  input.className = "cadetgui-field-input cadetgui-field-input-text";
  input.value = model.get("value");
  input.addEventListener("change", () => {
    model.set("value", input.value);
    model.save_changes();
  });
  wrap.appendChild(input);
  wrap.appendChild(fieldUnit(model));
  wrap.appendChild(fieldError(model, input));

  model.on("change:value", () => { input.value = model.get("value"); });
  bindDisabled(model, wrap);

  el.appendChild(wrap);
}

export default { render };
