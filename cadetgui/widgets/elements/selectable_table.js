function render({ model, el }) {
  const wrap = document.createElement("div");
  wrap.className = "cadetgui-table";

  const caption = document.createElement("div");
  caption.className = "cadetgui-table-caption";
  wrap.appendChild(caption);

  const scroll = document.createElement("div");
  scroll.className = "cadetgui-table-scroll";
  wrap.appendChild(scroll);

  const err = document.createElement("span");
  err.className = "cadetgui-field-error";
  wrap.appendChild(err);

  let rowEls = [];

  function select(i) {
    if (i < 0 || i >= rowEls.length) return;
    model.set("selected_index", i);
    model.save_changes();
  }

  function syncSelection() {
    const idx = model.get("selected_index");
    rowEls.forEach((row, i) => {
      const on = i === idx;
      row.classList.toggle("is-selected", on);
      row.setAttribute("aria-selected", String(on));
      row.tabIndex = on || (idx === null && i === 0) ? 0 : -1;
    });
    const current = idx === null ? null : rowEls[idx];
    if (current) current.scrollIntoView({ block: "nearest" });
  }

  function syncRows() {
    scroll.replaceChildren();
    rowEls = [];
    const columns = model.get("columns") || [];
    const rows = model.get("rows") || [];

    if (!rows.length) {
      const empty = document.createElement("div");
      empty.className = "cadetgui-table-empty";
      empty.textContent = model.get("empty_text");
      scroll.appendChild(empty);
      return;
    }

    const table = document.createElement("table");
    table.className = "cadetgui-table-grid";
    table.setAttribute("role", "grid");

    if (columns.length) {
      const thead = document.createElement("thead");
      const tr = document.createElement("tr");
      for (const name of columns) {
        const th = document.createElement("th");
        th.scope = "col";
        th.textContent = name;
        tr.appendChild(th);
      }
      thead.appendChild(tr);
      table.appendChild(thead);
    }

    const tbody = document.createElement("tbody");
    rows.forEach((cells, i) => {
      const tr = document.createElement("tr");
      tr.setAttribute("role", "row");
      for (const cell of cells) {
        const td = document.createElement("td");
        if (cell.chip) {
          const chip = document.createElement("span");
          chip.className = `cadetgui-chip cadetgui-chip-${cell.chip}`;
          chip.textContent = cell.text;
          td.appendChild(chip);
        } else {
          td.textContent = cell.text;
        }
        tr.appendChild(td);
      }
      tr.addEventListener("click", () => select(i));
      tr.addEventListener("keydown", (ev) => {
        let target = null;
        if (ev.key === "ArrowDown") target = i + 1;
        else if (ev.key === "ArrowUp") target = i - 1;
        else if (ev.key === "Home") target = 0;
        else if (ev.key === "End") target = rowEls.length - 1;
        else if (ev.key === "Enter" || ev.key === " ") target = i;
        if (target === null) return;
        ev.preventDefault();
        select(target);
        if (rowEls[target]) rowEls[target].focus();
      });
      tbody.appendChild(tr);
      rowEls.push(tr);
    });
    table.appendChild(tbody);
    scroll.appendChild(table);
    syncSelection();
  }

  function syncLabel() {
    caption.textContent = model.get("label");
    caption.hidden = !model.get("label");
  }

  function syncError() {
    const msg = model.get("error");
    err.textContent = msg;
    err.hidden = !msg;
  }

  syncLabel();
  syncRows();
  syncError();

  model.on("change:rows", syncRows);
  model.on("change:columns", syncRows);
  model.on("change:empty_text", syncRows);
  model.on("change:selected_index", syncSelection);
  model.on("change:label", syncLabel);
  model.on("change:error", syncError);

  el.appendChild(wrap);
}

export default { render };
