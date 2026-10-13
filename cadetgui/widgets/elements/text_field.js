function render({ model, el }) {
  const wrap = document.createElement("label");
  wrap.className = "cadetgui-field";
  wrap.appendChild(fieldLabel(model));

  const input = document.createElement("input");
  input.type = "text";
  const compact = model.get("compact");
  input.className = compact
    ? "cadetgui-field-input cadetgui-field-input-compact"
    : "cadetgui-field-input cadetgui-field-input-text";
  const fit = () => { if (compact) input.size = Math.max(10, input.value.length + 2); };
  input.value = model.get("value");
  fit();
  input.addEventListener("input", fit);
  input.addEventListener("change", () => {
    model.set("value", input.value);
    model.save_changes();
  });
  wrap.appendChild(input);
  wrap.appendChild(fieldUnit(model));
  wrap.appendChild(fieldError(model, input));

  model.on("change:value", () => { input.value = model.get("value"); fit(); });
  bindDisabled(model, wrap);

  el.appendChild(wrap);
}

export default { render };
