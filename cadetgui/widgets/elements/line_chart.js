// Categorical palette slots 1-5 from the project's dataviz reference
// palette (validated fixed order -- do not reorder or cycle).
const PALETTE_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"];
const PALETTE_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"];
const REFERENCE_LIGHT = "#111827";
const REFERENCE_DARK = "#f3f4f6";

const SVG_NS = "http://www.w3.org/2000/svg";
const PAD_L = 44;
const PAD_R = 10;
const PAD_R_AXIS = 46;
const PAD_T = 18;
const PAD_B = 38;
const MIN_DRAG_PX = 6;

function isDark() {
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function colorFor(s, i) {
  if (s.reference) return isDark() ? REFERENCE_DARK : REFERENCE_LIGHT;
  const pal = isDark() ? PALETTE_DARK : PALETTE_LIGHT;
  return pal[(s.color_index ?? i) % pal.length];
}

// Time-axis ticks land on whole/half minutes for coarse ranges and on decimal
// steps only once zoomed in far enough to need them.
const NICE_MINUTE_STEPS = [
  0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2,
  0.5, 1, 2, 5, 10, 15, 30, 60, 120, 180, 300, 600, 900, 1800, 3600,
];

function niceMinuteTicks(tMin, tMax, targetCount) {
  const span = tMax - tMin;
  if (!(span > 0)) return [tMin];
  const raw = span / Math.max(targetCount, 1);
  const step = NICE_MINUTE_STEPS.find((s) => s >= raw) || NICE_MINUTE_STEPS[NICE_MINUTE_STEPS.length - 1];
  const ticks = [];
  const start = Math.ceil(tMin / step) * step;
  for (let t = start; t <= tMax + step * 1e-6; t += step) ticks.push(Math.round(t * 1e6) / 1e6);
  return ticks.length ? ticks : [tMin];
}

// Same LaTeX-subset parser as the form fields' renderUnit() (float_field.js
// etc.), emitting SVG tspans since SVG text has no <sup>/<sub>. Duplicated,
// not imported -- every element ships its own view, no cross-file JS deps in
// this project.
// Parses the LaTeX subset units are written in (^ _ {} \mathrm \cdot \frac)
// into [{ text } | { sup: nodes } | { sub: nodes }]. \frac is flattened to
// "a/b", with the denominator parenthesised when compound, so a unit stays
// on one line.
function parseUnit(src) {
  const symbols = { cdot: "·", times: "×", ",": " ", " ": " " };
  const textCommands = ["mathrm", "text", "textrm"];
  let i = 0;

  const append = (out, nodes) => {
    for (const node of nodes) {
      const last = out[out.length - 1];
      if (node.text !== undefined && last && last.text !== undefined) last.text += node.text;
      else out.push(node);
    }
  };
  const hasTopLevel = (nodes, chars) =>
    nodes.some((n) => n.text !== undefined && [...chars].some((c) => n.text.includes(c)));
  const paren = (nodes, needed) =>
    needed ? [{ text: "(" }, ...nodes, { text: ")" }] : nodes;

  function parseArg() {
    while (src[i] === " ") i++;
    if (i >= src.length) return [];
    if (src[i] === "{") {
      i++;
      return parseSeq(true);
    }
    const out = [];
    if (src[i] === "\\") {
      parseCommand(out);
    } else {
      append(out, [{ text: src[i] }]);
      i++;
    }
    return out;
  }

  function parseCommand(out) {
    i++;
    const letters = /^[A-Za-z]+/.exec(src.slice(i));
    const name = letters ? letters[0] : src.charAt(i);
    i += name.length;
    if (letters) while (src[i] === " ") i++;
    if (textCommands.includes(name)) {
      append(out, parseArg());
    } else if (name === "frac") {
      const num = parseArg();
      const den = parseArg();
      append(out, paren(num, hasTopLevel(num, "/")));
      append(out, [{ text: "/" }]);
      append(out, paren(den, hasTopLevel(den, "·×/")));
    } else if (name in symbols) {
      append(out, [{ text: symbols[name] }]);
    } else {
      append(out, [{ text: letters ? `\\${name}` : name || "\\" }]);
    }
  }

  function parseSeq(untilBrace) {
    const out = [];
    while (i < src.length) {
      const ch = src[i];
      if (ch === "}" && untilBrace) {
        i++;
        return out;
      }
      if (ch === "{") {
        i++;
        append(out, parseSeq(true));
      } else if (ch === "\\") {
        parseCommand(out);
      } else if (ch === "^" || ch === "_") {
        i++;
        out.push(ch === "^" ? { sup: parseArg() } : { sub: parseArg() });
      } else {
        append(out, [{ text: ch }]);
        i++;
      }
    }
    return out;
  }

  return parseSeq(false);
}

// baseline-shift per tspan, not dy + an empty reset tspan -- the latter
// doesn't reliably re-anchor the baseline for trailing plain text.
function appendUnitNodesSvg(parent, nodes) {
  for (const node of nodes) {
    if (node.text !== undefined) {
      parent.appendChild(document.createTextNode(node.text));
      continue;
    }
    const span = document.createElementNS(SVG_NS, "tspan");
    span.setAttribute("baseline-shift", node.sup ? "super" : "sub");
    span.setAttribute("font-size", "70%");
    appendUnitNodesSvg(span, node.sup || node.sub);
    parent.appendChild(span);
  }
}

function renderUnitSvg(textEl, raw) {
  while (textEl.firstChild) textEl.removeChild(textEl.firstChild);
  if (!raw) return;
  appendUnitNodesSvg(textEl, parseUnit(raw));
}

function formatTick(v) {
  if (!Number.isFinite(v)) return String(v);
  const abs = Math.abs(v);
  if (abs !== 0 && (abs < 1e-3 || abs >= 1e5)) return v.toExponential(1);
  return String(Math.round(v * 1000) / 1000);
}

function nearestIndex(times, t) {
  let lo = 0;
  let hi = times.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (times[mid] < t) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0 && Math.abs(times[lo - 1] - t) < Math.abs(times[lo] - t)) return lo - 1;
  return lo;
}

function svgEl(name, attrs) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, String(v));
  return node;
}

function makeScale(lo, hi, pxLo, pxHi) {
  const span = hi - lo || 1;
  return { lo, hi, span, px: (v) => pxLo + ((v - lo) / span) * (pxHi - pxLo) };
}

// Range of `values` whose time falls inside [xLo, xHi], padded 10% so lines
// never touch the frame; falls back to 0..1 with nothing to measure.
function paddedExtent(items, xLo, xHi) {
  let lo = Infinity;
  let hi = -Infinity;
  for (const s of items) {
    for (let j = 0; j < s.times.length; j++) {
      const t = s.times[j];
      if (t < xLo || t > xHi) continue;
      const v = s.values[j];
      if (!Number.isFinite(v)) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) {
    lo = 0;
    hi = 1;
  }
  if (lo === hi) {
    lo -= 1;
    hi += 1;
  }
  const pad = (hi - lo) * 0.1;
  return [lo - pad, hi + pad];
}

let clipCounter = 0;

function render({ model, el }) {
  const wrap = document.createElement("div");
  wrap.className = "cadetgui-chart";

  const svg = svgEl("svg", { class: "cadetgui-chart-svg", preserveAspectRatio: "xMidYMid meet" });
  wrap.appendChild(svg);

  const legend = document.createElement("div");
  legend.className = "cadetgui-chart-legend";
  wrap.appendChild(legend);

  const resetBtn = document.createElement("button");
  resetBtn.type = "button";
  resetBtn.className = "cadetgui-chart-reset";
  resetBtn.textContent = "Reset zoom";
  resetBtn.hidden = true;
  wrap.appendChild(resetBtn);

  const tooltip = document.createElement("div");
  tooltip.className = "cadetgui-chart-tooltip";
  tooltip.hidden = true;
  wrap.appendChild(tooltip);

  const clipId = `cadetgui-chart-clip-${clipCounter++}`;
  const state = { view: null, hidden: new Set() };

  resetBtn.addEventListener("click", () => {
    state.view = null;
    draw();
  });

  function draw() {
    svg.replaceChildren();
    legend.replaceChildren();
    tooltip.hidden = true;

    const W = model.get("view_width");
    const H = model.get("view_height");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

    const all = (model.get("series") || []).filter((s) => s.times && s.times.length);
    if (!all.length) {
      resetBtn.hidden = true;
      const msg = svgEl("text", {
        x: W / 2,
        y: H / 2,
        "text-anchor": "middle",
        class: "cadetgui-chart-empty",
      });
      msg.textContent = model.get("empty_text") || "";
      svg.appendChild(msg);
      return;
    }

    let tMin = Infinity;
    let tMax = -Infinity;
    for (const s of all) {
      tMin = Math.min(tMin, s.times[0]);
      tMax = Math.max(tMax, s.times[s.times.length - 1]);
    }
    if (state.view && (state.view[0] < tMin || state.view[1] > tMax || !(state.view[1] > state.view[0]))) {
      state.view = null;
    }
    const [xLo, xHi] = state.view || [tMin, tMax];
    resetBtn.hidden = !state.view;

    const hasRight = all.some((s) => s.axis === "right");
    const padR = hasRight ? PAD_R_AXIS : PAD_R;
    const plotW = W - PAD_L - padR;
    const plotH = H - PAD_T - PAD_B;

    const shown = all.filter((s) => !state.hidden.has(s.name));
    const [lLo, lHi] = paddedExtent(shown.filter((s) => s.axis !== "right"), xLo, xHi);
    const [rLo, rHi] = paddedExtent(shown.filter((s) => s.axis === "right"), xLo, xHi);
    const xScale = makeScale(xLo, xHi, PAD_L, PAD_L + plotW);
    const yLeft = makeScale(lLo, lHi, H - PAD_B, PAD_T);
    const yRight = makeScale(rLo, rHi, H - PAD_B, PAD_T);

    const title = svgEl("title");
    title.textContent = "Drag to zoom, double-click to reset";
    svg.appendChild(title);

    const gGrid = svgEl("g", { class: "cadetgui-chart-grid" });
    const NY = 4;
    for (let i = 0; i <= NY; i++) {
      const y = yLeft.px(yLeft.lo + (yLeft.span * i) / NY);
      gGrid.appendChild(svgEl("line", { x1: PAD_L, x2: PAD_L + plotW, y1: y, y2: y }));
      const label = svgEl("text", {
        x: PAD_L - 5,
        y,
        "text-anchor": "end",
        "dominant-baseline": "middle",
        class: "cadetgui-chart-axislabel",
      });
      label.textContent = formatTick(yLeft.lo + (yLeft.span * i) / NY);
      gGrid.appendChild(label);
      if (hasRight) {
        const rLabel = svgEl("text", {
          x: PAD_L + plotW + 5,
          y,
          "text-anchor": "start",
          "dominant-baseline": "middle",
          class: "cadetgui-chart-axislabel",
        });
        rLabel.textContent = formatTick(yRight.lo + (yRight.span * i) / NY);
        gGrid.appendChild(rLabel);
      }
    }
    svg.appendChild(gGrid);

    for (const t of niceMinuteTicks(xLo, xHi, 5)) {
      const label = svgEl("text", {
        x: xScale.px(t),
        y: H - PAD_B + 13,
        "text-anchor": "middle",
        class: "cadetgui-chart-axislabel",
      });
      label.textContent = formatTick(t);
      svg.appendChild(label);
    }

    const xTitle = svgEl("text", {
      x: PAD_L + plotW / 2,
      y: H - 4,
      "text-anchor": "middle",
      class: "cadetgui-chart-axistitle",
    });
    xTitle.textContent = model.get("x_label") || "";
    svg.appendChild(xTitle);

    const yTitle = svgEl("text", {
      x: PAD_L,
      y: PAD_T - 6,
      "text-anchor": "start",
      class: "cadetgui-chart-axistitle",
    });
    renderUnitSvg(yTitle, model.get("y_label") || "");
    svg.appendChild(yTitle);

    if (hasRight) {
      const yTitleRight = svgEl("text", {
        x: PAD_L + plotW,
        y: PAD_T - 6,
        "text-anchor": "end",
        class: "cadetgui-chart-axistitle",
      });
      renderUnitSvg(yTitleRight, model.get("y_label_right") || "");
      svg.appendChild(yTitleRight);
    }

    const clip = svgEl("clipPath", { id: clipId });
    clip.appendChild(svgEl("rect", { x: PAD_L, y: PAD_T, width: plotW, height: plotH }));
    svg.appendChild(clip);
    const gData = svgEl("g", { "clip-path": `url(#${clipId})` });
    svg.appendChild(gData);

    const scaleFor = (s) => (s.axis === "right" ? yRight : yLeft);
    const pathFor = (s) => {
      const y = scaleFor(s);
      let d = "";
      for (let j = 0; j < s.times.length; j++) {
        d += `${j === 0 ? "M" : "L"} ${xScale.px(s.times[j])} ${y.px(s.values[j])} `;
      }
      return d.trim();
    };

    // Area washes first so a wash never paints over another series' line.
    all.forEach((s, i) => {
      if (state.hidden.has(s.name) || s.dashed || s.axis === "right") return;
      const base = yLeft.px(yLeft.lo);
      const area = svgEl("path", {
        d: `${pathFor(s)} L ${xScale.px(s.times[s.times.length - 1])} ${base} L ${xScale.px(s.times[0])} ${base} Z`,
        class: "cadetgui-chart-area",
        fill: colorFor(s, i),
      });
      gData.appendChild(area);
    });

    all.forEach((s, i) => {
      const color = colorFor(s, i);
      const off = state.hidden.has(s.name);
      if (!off) {
        const path = svgEl("path", { d: pathFor(s), class: "cadetgui-chart-line", stroke: color });
        if (s.dashed) path.setAttribute("stroke-dasharray", "5 3");
        gData.appendChild(path);
      }

      const item = document.createElement("button");
      item.type = "button";
      item.className = "cadetgui-chart-legend-item" + (off ? " is-off" : "");
      item.setAttribute("aria-pressed", String(!off));
      const swatch = document.createElement("span");
      swatch.className = "cadetgui-chart-legend-swatch";
      swatch.style.background = s.dashed
        ? `repeating-linear-gradient(90deg, ${color} 0 5px, transparent 5px 8px)`
        : color;
      const name = document.createElement("span");
      name.textContent = s.name;
      item.appendChild(swatch);
      item.appendChild(name);
      item.addEventListener("click", () => {
        if (state.hidden.has(s.name)) state.hidden.delete(s.name);
        else state.hidden.add(s.name);
        draw();
      });
      legend.appendChild(item);
    });

    const crosshair = svgEl("line", { class: "cadetgui-chart-crosshair", y1: PAD_T, y2: H - PAD_B });
    crosshair.style.display = "none";
    svg.appendChild(crosshair);

    const selection = svgEl("rect", { class: "cadetgui-chart-selection", y: PAD_T, height: plotH });
    selection.style.display = "none";
    svg.appendChild(selection);

    const capture = svgEl("rect", {
      x: PAD_L,
      y: PAD_T,
      width: Math.max(plotW, 0),
      height: Math.max(plotH, 0),
      fill: "transparent",
    });
    capture.style.cursor = "crosshair";
    svg.appendChild(capture);

    const toPx = (ev) => {
      const rect = svg.getBoundingClientRect();
      return ((ev.clientX - rect.left) / rect.width) * W;
    };
    const toTime = (px) => {
      const t = xLo + ((px - PAD_L) / plotW) * (xHi - xLo);
      return Math.max(xLo, Math.min(xHi, t));
    };

    let dragStart = null;

    function showTooltip(ev, t) {
      const xPix = xScale.px(t);
      crosshair.setAttribute("x1", String(xPix));
      crosshair.setAttribute("x2", String(xPix));
      crosshair.style.display = "";

      tooltip.replaceChildren();
      const timeRow = document.createElement("div");
      timeRow.className = "cadetgui-chart-tooltip-time";
      timeRow.textContent = `t = ${formatTick(t)} min`;
      tooltip.appendChild(timeRow);
      all.forEach((s, i) => {
        if (state.hidden.has(s.name)) return;
        const idx = nearestIndex(s.times, t);
        const row = document.createElement("div");
        row.className = "cadetgui-chart-tooltip-row";
        const key = document.createElement("span");
        key.className = "cadetgui-chart-tooltip-key";
        key.style.background = colorFor(s, i);
        const val = document.createElement("span");
        val.className = "cadetgui-chart-tooltip-value";
        val.textContent = formatTick(s.values[idx]);
        const name = document.createElement("span");
        name.className = "cadetgui-chart-tooltip-name";
        name.textContent = s.name;
        row.appendChild(key);
        row.appendChild(val);
        row.appendChild(name);
        tooltip.appendChild(row);
      });
      tooltip.hidden = false;

      const wrapRect = wrap.getBoundingClientRect();
      let left = ev.clientX - wrapRect.left + 14;
      const top = ev.clientY - wrapRect.top + 14;
      if (left + 170 > wrapRect.width) left = ev.clientX - wrapRect.left - 180;
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${top}px`;
    }

    capture.addEventListener("pointerdown", (ev) => {
      dragStart = toPx(ev);
      capture.setPointerCapture(ev.pointerId);
    });

    capture.addEventListener("pointermove", (ev) => {
      const px = toPx(ev);
      if (dragStart !== null && Math.abs(px - dragStart) > MIN_DRAG_PX) {
        const a = Math.max(PAD_L, Math.min(px, dragStart));
        const b = Math.min(PAD_L + plotW, Math.max(px, dragStart));
        selection.setAttribute("x", String(a));
        selection.setAttribute("width", String(Math.max(b - a, 0)));
        selection.style.display = "";
        crosshair.style.display = "none";
        tooltip.hidden = true;
        return;
      }
      showTooltip(ev, toTime(px));
    });

    capture.addEventListener("pointerup", (ev) => {
      const start = dragStart;
      dragStart = null;
      selection.style.display = "none";
      if (start === null) return;
      const end = toPx(ev);
      if (Math.abs(end - start) <= MIN_DRAG_PX) return;
      const t0 = toTime(Math.min(start, end));
      const t1 = toTime(Math.max(start, end));
      if (t1 > t0) {
        state.view = [t0, t1];
        draw();
      }
    });

    capture.addEventListener("pointerleave", () => {
      crosshair.style.display = "none";
      tooltip.hidden = true;
    });

    capture.addEventListener("dblclick", () => {
      state.view = null;
      draw();
    });
  }

  draw();
  for (const name of ["series", "x_label", "y_label", "y_label_right", "empty_text", "view_width", "view_height"]) {
    model.on(`change:${name}`, draw);
  }
  el.appendChild(wrap);
}

export default { render };
