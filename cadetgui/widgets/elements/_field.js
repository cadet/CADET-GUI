function fieldLabel(model) {
  const el = document.createElement("span");
  el.className = "cadetgui-field-label";
  const sync = () => {
    el.textContent = model.get("label");
    el.title = model.get("label");
  };
  sync();
  model.on("change:label", sync);
  return el;
}

function fieldError(model, input) {
  const el = document.createElement("span");
  el.className = "cadetgui-field-error";
  const sync = () => {
    const msg = model.get("error");
    el.textContent = msg;
    el.hidden = !msg;
    if (input) input.setAttribute("aria-invalid", msg ? "true" : "false");
  };
  sync();
  model.on("change:error", sync);
  return el;
}

// Returns the sync function so a view that rebuilds its rows can re-apply it.
function bindDisabled(model, wrap) {
  const sync = () => {
    const off = Boolean(model.get("disabled"));
    wrap.classList.toggle("cadetgui-field-disabled", off);
    wrap.querySelectorAll("input, select, button").forEach((n) => { n.disabled = off; });
  };
  sync();
  model.on("change:disabled", sync);
  return sync;
}

function formatNumber(n) {
  if (!Number.isFinite(n) || n === 0) return String(n);
  const abs = Math.abs(n);
  if (abs < 1e-3 || abs >= 1e6) return n.toExponential();
  return String(n);
}
