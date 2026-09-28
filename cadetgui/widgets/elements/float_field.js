function render({ model, el }) {
  const wrap = document.createElement("label");
  wrap.className = "cadetgui-field";
  wrap.appendChild(fieldLabel(model));

  const input = document.createElement("input");
  input.type = "number";
  input.step = "any";
  input.className = "cadetgui-field-input";

  const syncBounds = () => {
    const min = model.get("min");
    const max = model.get("max");
    if (min == null) input.removeAttribute("min");
    else input.min = String(min);
    if (max == null) input.removeAttribute("max");
    else input.max = String(max);
  };
  const syncValue = () => {
    input.value = formatNumber(model.get("value"));
  };
  syncBounds();
  syncValue();

  input.addEventListener("change", () => {
    const parsed = parseFloat(input.value);
    if (!Number.isNaN(parsed)) {
      model.set("value", parsed);
      model.save_changes();
    }
  });
  wrap.appendChild(input);
  wrap.appendChild(fieldUnit(model));
  wrap.appendChild(fieldError(model, input));

  model.on("change:value", syncValue);
  model.on("change:min", syncBounds);
  model.on("change:max", syncBounds);
  bindDisabled(model, wrap);

  el.appendChild(wrap);
}

export default { render };
