// Categorical palette slots 1-5 from the project's dataviz reference
// palette (validated fixed order -- do not reorder or cycle).
const PALETTE_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"];
const PALETTE_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"];

const SVG_NS = "http://www.w3.org/2000/svg";
const W = 480;
const H = 220;
const PAD_L = 44;
const PAD_R = 10;
const PAD_T = 18;
const PAD_B = 38;

function isDark() {
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function colorFor(i) {
  const pal = isDark() ? PALETTE_DARK : PALETTE_LIGHT;
  return pal[i % pal.length];
}

// Time-axis ticks always land on a whole or half minute -- never a "wild"
// fractional value from naively splitting the range into N equal steps.
const NICE_MINUTE_STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 180, 300, 600, 900, 1800, 3600];

function niceMinuteTicks(tMin, tMax, targetCount) {
  const span = tMax - tMin;
  if (!(span > 0)) return [tMin];
  const raw = span / Math.max(targetCount, 1);
  const step = NICE_MINUTE_STEPS.find((s) => s >= raw) || NICE_MINUTE_STEPS[NICE_MINUTE_STEPS.length - 1];
  const ticks = [];
  const start = Math.ceil(tMin / step) * step;
  for (let t = start; t <= tMax + step * 1e-6; t += step) ticks.push(Math.round(t * 1000) / 1000);
  return ticks.length ? ticks : [tMin];
}

// Same `^digits` (superscript) / `_word` (subscript) / `*` (middot) tokens
// as the form fields' renderUnit() (float_field.js etc.), ported to SVG
// tspans since SVG text has no <sup>/<sub>. Duplicated, not imported --
// every element ships its own view, no cross-file JS deps in this project.
// Uses baseline-shift per tspan, not dy + an empty reset tspan -- the
// latter doesn't reliably re-anchor the baseline for trailing plain text.
function renderUnitSvg(textEl, raw) {
  while (textEl.firstChild) textEl.removeChild(textEl.firstChild);
  if (!raw) return;
  const re = /\^([0-9]+)|_([A-Za-z0-9]+)|\*/g;
  let last = 0;
  let m;
  while ((m = re.exec(raw)) !== null) {
    if (m.index > last) textEl.appendChild(document.createTextNode(raw.slice(last, m.index)));
    if (m[1] !== undefined) {
      const up = document.createElementNS(SVG_NS, "tspan");
      up.setAttribute("baseline-shift", "super");
      up.setAttribute("font-size", "70%");
      up.textContent = m[1];
      textEl.appendChild(up);
    } else if (m[2] !== undefined) {
      const down = document.createElementNS(SVG_NS, "tspan");
      down.setAttribute("baseline-shift", "sub");
      down.setAttribute("font-size", "70%");
      down.textContent = m[2];
      textEl.appendChild(down);
    } else {
      textEl.appendChild(document.createTextNode("·"));
    }
    last = re.lastIndex;
  }
  if (last < raw.length) textEl.appendChild(document.createTextNode(raw.slice(last)));
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

function render({ model, el }) {
  const wrap = document.createElement("div");
  wrap.className = "cadetgui-timeline-chart";

  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "cadetgui-timeline-svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  wrap.appendChild(svg);

  const legend = document.createElement("div");
  legend.className = "cadetgui-timeline-legend";
  wrap.appendChild(legend);

  const tooltip = document.createElement("div");
  tooltip.className = "cadetgui-timeline-tooltip";
  tooltip.hidden = true;
  wrap.appendChild(tooltip);

  function draw() {
    svg.replaceChildren();
    legend.replaceChildren();
    tooltip.hidden = true;

    const series = model.get("series") || [];
    if (!series.length || !series[0].times || !series[0].times.length) {
      const msg = document.createElementNS(SVG_NS, "text");
      msg.setAttribute("x", String(W / 2));
      msg.setAttribute("y", String(H / 2));
      msg.setAttribute("text-anchor", "middle");
      msg.setAttribute("class", "cadetgui-timeline-empty");
      msg.textContent = "No events yet";
      svg.appendChild(msg);
      return;
    }

    const times = series[0].times;
    const tMin = times[0];
    const tMax = times[times.length - 1];
    let vMin = Infinity;
    let vMax = -Infinity;
    for (const s of series) {
      for (const v of s.values) {
        if (v < vMin) vMin = v;
        if (v > vMax) vMax = v;
      }
    }
    if (!Number.isFinite(vMin) || !Number.isFinite(vMax)) {
      vMin = 0;
      vMax = 1;
    }
    if (vMin === vMax) {
      vMin -= 1;
      vMax += 1;
    }
    const vPad = (vMax - vMin) * 0.1;
    vMin -= vPad;
    vMax += vPad;
    const tSpan = tMax - tMin || 1;
    const vSpan = vMax - vMin || 1;

    const xScale = (t) => PAD_L + ((t - tMin) / tSpan) * (W - PAD_L - PAD_R);
    const yScale = (v) => H - PAD_B - ((v - vMin) / vSpan) * (H - PAD_T - PAD_B);

    const gGrid = document.createElementNS(SVG_NS, "g");
    gGrid.setAttribute("class", "cadetgui-timeline-grid");
    const NY = 4;
    for (let i = 0; i <= NY; i++) {
      const v = vMin + (vSpan * i) / NY;
      const y = yScale(v);
      const line = document.createElementNS(SVG_NS, "line");
      line.setAttribute("x1", String(PAD_L));
      line.setAttribute("x2", String(W - PAD_R));
      line.setAttribute("y1", String(y));
      line.setAttribute("y2", String(y));
      gGrid.appendChild(line);
      const label = document.createElementNS(SVG_NS, "text");
      label.setAttribute("x", String(PAD_L - 5));
      label.setAttribute("y", String(y));
      label.setAttribute("text-anchor", "end");
      label.setAttribute("dominant-baseline", "middle");
      label.setAttribute("class", "cadetgui-timeline-axislabel");
      label.textContent = formatTick(v);
      gGrid.appendChild(label);
    }
    svg.appendChild(gGrid);

    for (const t of niceMinuteTicks(tMin, tMax, 5)) {
      const label = document.createElementNS(SVG_NS, "text");
      label.setAttribute("x", String(xScale(t)));
      label.setAttribute("y", String(H - PAD_B + 13));
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("class", "cadetgui-timeline-axislabel");
      label.textContent = formatTick(t);
      svg.appendChild(label);
    }

    const xTitle = document.createElementNS(SVG_NS, "text");
    xTitle.setAttribute("x", String((PAD_L + (W - PAD_R)) / 2));
    xTitle.setAttribute("y", String(H - 4));
    xTitle.setAttribute("text-anchor", "middle");
    xTitle.setAttribute("class", "cadetgui-timeline-axistitle");
    xTitle.textContent = model.get("x_label") || "";
    svg.appendChild(xTitle);

    const yTitle = document.createElementNS(SVG_NS, "text");
    yTitle.setAttribute("x", String(PAD_L));
    yTitle.setAttribute("y", String(PAD_T - 6));
    yTitle.setAttribute("text-anchor", "start");
    yTitle.setAttribute("class", "cadetgui-timeline-axistitle");
    renderUnitSvg(yTitle, model.get("y_label") || "");
    svg.appendChild(yTitle);

    // Area-fill wash under each line first, so a wash never paints over
    // another series' line; strokes go in a second pass on top.
    const baseline = yScale(vMin);
    series.forEach((s, i) => {
      const color = colorFor(i);
      let areaD = `M ${xScale(s.times[0])} ${baseline} `;
      for (let j = 0; j < s.times.length; j++) {
        areaD += `L ${xScale(s.times[j])} ${yScale(s.values[j])} `;
      }
      areaD += `L ${xScale(s.times[s.times.length - 1])} ${baseline} Z`;
      const area = document.createElementNS(SVG_NS, "path");
      area.setAttribute("d", areaD);
      area.setAttribute("class", "cadetgui-timeline-area");
      area.setAttribute("fill", color);
      svg.appendChild(area);
    });

    series.forEach((s, i) => {
      const color = colorFor(i);
      let d = "";
      for (let j = 0; j < s.times.length; j++) {
        const cmd = j === 0 ? "M" : "L";
        d += `${cmd} ${xScale(s.times[j])} ${yScale(s.values[j])} `;
      }
      const path = document.createElementNS(SVG_NS, "path");
      path.setAttribute("d", d.trim());
      path.setAttribute("class", "cadetgui-timeline-line");
      path.setAttribute("stroke", color);
      svg.appendChild(path);

      const item = document.createElement("div");
      item.className = "cadetgui-timeline-legend-item";
      const swatch = document.createElement("span");
      swatch.className = "cadetgui-timeline-legend-swatch";
      swatch.style.background = color;
      const name = document.createElement("span");
      name.textContent = s.name;
      item.appendChild(swatch);
      item.appendChild(name);
      legend.appendChild(item);
    });

    const crosshair = document.createElementNS(SVG_NS, "line");
    crosshair.setAttribute("class", "cadetgui-timeline-crosshair");
    crosshair.setAttribute("y1", String(PAD_T));
    crosshair.setAttribute("y2", String(H - PAD_B));
    crosshair.style.display = "none";
    svg.appendChild(crosshair);

    const capture = document.createElementNS(SVG_NS, "rect");
    capture.setAttribute("x", String(PAD_L));
    capture.setAttribute("y", String(PAD_T));
    capture.setAttribute("width", String(Math.max(W - PAD_L - PAD_R, 0)));
    capture.setAttribute("height", String(Math.max(H - PAD_T - PAD_B, 0)));
    capture.setAttribute("fill", "transparent");
    capture.style.cursor = "crosshair";
    svg.appendChild(capture);

    function onMove(ev) {
      const rect = svg.getBoundingClientRect();
      const px = ((ev.clientX - rect.left) / rect.width) * W;
      const t = tMin + ((px - PAD_L) / (W - PAD_L - PAD_R)) * tSpan;
      const clamped = Math.max(tMin, Math.min(tMax, t));
      const idx = nearestIndex(times, clamped);
      const xPix = xScale(times[idx]);
      crosshair.setAttribute("x1", String(xPix));
      crosshair.setAttribute("x2", String(xPix));
      crosshair.style.display = "";

      tooltip.replaceChildren();
      const timeRow = document.createElement("div");
      timeRow.className = "cadetgui-timeline-tooltip-time";
      timeRow.textContent = `t = ${formatTick(times[idx])} min`;
      tooltip.appendChild(timeRow);
      series.forEach((s, i) => {
        const row = document.createElement("div");
        row.className = "cadetgui-timeline-tooltip-row";
        const key = document.createElement("span");
        key.className = "cadetgui-timeline-tooltip-key";
        key.style.background = colorFor(i);
        const val = document.createElement("span");
        val.className = "cadetgui-timeline-tooltip-value";
        val.textContent = formatTick(s.values[idx]);
        const name = document.createElement("span");
        name.className = "cadetgui-timeline-tooltip-name";
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

    capture.addEventListener("pointermove", onMove);
    capture.addEventListener("pointerleave", () => {
      crosshair.style.display = "none";
      tooltip.hidden = true;
    });
  }

  draw();
  model.on("change:series", draw);
  model.on("change:x_label", draw);
  model.on("change:y_label", draw);
  el.appendChild(wrap);
}

export default { render };
