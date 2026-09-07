function render({ model, el }) {
  const wrap = document.createElement("label");
  wrap.className = "cadetgui-field";

  const labelEl = document.createElement("span");
  labelEl.className = "cadetgui-field-label";
  labelEl.textContent = model.get("label");
  wrap.appendChild(labelEl);

  const input = document.createElement("input");
  input.type = "number";
  input.step = "any";
  input.className = "cadetgui-field-input";

  const syncBounds = () => {
    const min = model.get("min");
    const max = model.get("max");
    if (min === null || min === undefined) input.removeAttribute("min");
    else input.min = String(min);
    if (max === null || max === undefined) input.removeAttribute("max");
    else input.max = String(max);
  };
  const syncValue = () => {
    input.value = model.get("value");
  };
  const syncError = () => {
    const msg = model.get("error");
    err.textContent = msg;
    err.hidden = !msg;
    input.setAttribute("aria-invalid", msg ? "true" : "false");
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

  const err = document.createElement("span");
  err.className = "cadetgui-field-error";
  wrap.appendChild(err);
  syncError();

  model.on("change:value", syncValue);
  model.on("change:min", syncBounds);
  model.on("change:max", syncBounds);
  model.on("change:error", syncError);
  model.on("change:label", () => { labelEl.textContent = model.get("label"); });

  el.appendChild(wrap);
}

export default { render };
