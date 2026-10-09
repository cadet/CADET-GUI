// Draggable cubic: four handles at 0, T/3, 2T/3 and T of the first section.
// Python solves for the coefficients when a handle is released.
const SVG_NS = "http://www.w3.org/2000/svg";
const W = 480;
const H = 220;
const PAD = { l: 58, r: 14, t: 16, b: 42 };
const COLOR = "#4a7fb5";

function el(name, attrs, parent) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

function formatTick(v) {
  const abs = Math.abs(v);
  if (abs !== 0 && (abs < 1e-3 || abs >= 1e5)) return v.toExponential(1);
  return String(Math.round(v * 1000) / 1000);
}

function ticks(lo, hi, count) {
  const span = hi - lo;
  if (!(span > 0)) return [lo];
  const raw = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(v);
  return out;
}

// Value at t of the cubic through (times[k], values[k]), by Lagrange interpolation.
function lagrange(times, values, t) {
  let sum = 0;
  for (let i = 0; i < times.length; i++) {
    let term = values[i];
    for (let j = 0; j < times.length; j++) {
      if (j !== i) term *= (t - times[j]) / (times[i] - times[j]);
    }
    sum += term;
  }
  return sum;
}

function render({ model, el: root }) {
  const wrap = document.createElement("div");
  wrap.className = "cadetgui-chart";
  wrap.style.maxWidth = "560px";
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "cadetgui-chart-svg" }, wrap);
  root.appendChild(wrap);

  let drag = null;

  function draw() {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    const duration = model.get("duration");
    const points = drag ? drag.points : model.get("points");
    const curve = model.get("curve");
    const cycle = model.get("cycle_time");
    const handleTimes = [0, duration / 3, (2 * duration) / 3, duration];

    const values = curve.values.concat(points);
    let lo = Math.min(0, ...values);
    let hi = Math.max(...values);
    if (!(hi > lo)) hi = lo + 1;
    hi += (hi - lo) * 0.15;
    const x = (t) => PAD.l + (t / cycle) * (W - PAD.l - PAD.r);
    const y = (v) => H - PAD.b - ((v - lo) / (hi - lo)) * (H - PAD.t - PAD.b);

    const grid = el("g", { class: "cadetgui-chart-grid" }, svg);
    for (const v of ticks(lo, hi, 4)) {
      el("line", { x1: PAD.l, x2: W - PAD.r, y1: y(v), y2: y(v) }, grid);
      el("text", { x: PAD.l - 12, y: y(v) + 4, "text-anchor": "end", class: "cadetgui-chart-axislabel" }, svg)
        .textContent = formatTick(v);
    }
    for (const t of ticks(0, cycle / 60, 6)) {
      el("text", { x: x(t * 60), y: H - PAD.b + 18, "text-anchor": "middle", class: "cadetgui-chart-axislabel" }, svg)
        .textContent = formatTick(t);
    }
    el("text", { x: (PAD.l + W - PAD.r) / 2, y: H - 6, "text-anchor": "middle", class: "cadetgui-chart-axistitle" }, svg)
      .textContent = "Time / min";
    const title = el("text", { x: 12, y: (PAD.t + H - PAD.b) / 2, "text-anchor": "middle", class: "cadetgui-chart-axistitle",
      transform: `rotate(-90 12 ${(PAD.t + H - PAD.b) / 2})` }, svg);
    title.textContent = model.get("y_label");

    let d = "";
    if (drag) {
      for (let i = 0; i <= 60; i++) {
        const t = (duration * i) / 60;
        d += `${i ? "L" : "M"}${x(t)} ${y(lagrange(handleTimes, points, t))}`;
      }
    } else {
      curve.times.forEach((t, i) => { d += `${i ? "L" : "M"}${x(t)} ${y(curve.values[i])}`; });
    }
    el("path", { d, fill: "none", stroke: COLOR, "stroke-width": 2.5 }, svg);

    handleTimes.forEach((t, i) => {
      const handle = el("circle", { cx: x(t), cy: y(points[i]), r: 7, fill: "#ffffff", stroke: COLOR,
        "stroke-width": 2.5, style: "cursor: ns-resize" }, svg);
      handle.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        handle.setPointerCapture(event.pointerId);
        drag = { index: i, points: points.slice(), lo, hi };
      });
      handle.addEventListener("pointermove", (event) => {
        if (!drag || drag.index !== i) return;
        const box = svg.getBoundingClientRect();
        const py = ((event.clientY - box.top) / box.height) * H;
        const v = drag.lo + ((H - PAD.b - py) / (H - PAD.t - PAD.b)) * (drag.hi - drag.lo);
        drag.points[i] = v;
        draw();
      });
      handle.addEventListener("pointerup", () => {
        if (!drag) return;
        model.set("points", drag.points);
        model.save_changes();
        drag = null;
      });
    });
  }

  draw();
  for (const name of ["points", "curve", "duration", "cycle_time", "y_label"]) {
    model.on(`change:${name}`, () => { if (!drag) draw(); });
  }
}

export default { render };
