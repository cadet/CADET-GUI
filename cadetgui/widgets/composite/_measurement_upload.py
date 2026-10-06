"""The upload page of the add-measurement stepper: read a run file or pick a loaded run."""

from __future__ import annotations

import html
from typing import Any, Dict, List, Optional, Tuple

import ipywidgets as W

from ...experimental_data import (
    ExperimentalRun,
    detect_column_roles,
    is_akta_format,
    read_akta_csv,
    read_generic_csv,
    read_headers,
)
from .._status import status_html
from ..elements import ChoiceField
from ._measurement_common import COLUMN_ROLE_OPTIONS, _note, _row


def _upload_items(value: Any) -> List[dict]:
    """Return the uploaded files as dicts with `name` and `content` (ipywidgets 7 and 8)."""
    if isinstance(value, dict):
        return [{"name": name, **item} for name, item in value.items()]
    return list(value)


class _RunUpload:
    """Upload page of `AddMeasurementFlow`; sets `run` and `data_file`.

    The host provides `_runs()` and `_loading`.
    """

    def _init_upload(self) -> W.VBox:
        """Create the page's controls and return the page."""
        self.uploaded: Dict[str, ExperimentalRun] = {}
        self.run: Optional[ExperimentalRun] = None
        self.data_file = ""
        self._pending: Optional[Tuple[str, bytes]] = None
        self._role_dropdowns: List[W.Dropdown] = []

        self._upload = W.FileUpload(
            accept=".csv,.txt,.tsv", multiple=False, description="Upload run"
        )
        self._time_unit = ChoiceField(
            label="A 2-column file's time is in:",
            options=[("minutes", "min"), ("seconds", "s")],
        )
        self._loaded = ChoiceField(label="Or use a loaded run:")
        self._roles_box = W.VBox([])
        self._btn_roles = W.Button(description="Use these columns", icon="check")
        self._run_note = W.HTML()

        self._upload.observe(self._on_upload, names="value")
        self._loaded.observe(self._on_pick_loaded, names="selected_index")
        self._btn_roles.on_click(lambda _b: self._apply_roles())
        return W.VBox([
            _note("Upload the run's export (CSV, TXT or TSV). ÄKTA/Unicorn exports are "
                  "recognized automatically. Other tables work too: comma, semicolon or "
                  "tab separated, decimal commas, lines above the header row are skipped; "
                  "you say which column is time or volume."),
            _row(self._upload, self._time_unit),
            self._roles_box,
            _row(self._loaded),
            self._run_note,
        ])

    def _on_upload(self, _change: dict) -> None:
        if not self._upload.value:
            return
        for item in _upload_items(self._upload.value):
            self.load_bytes(item["name"], bytes(item["content"]))
        self._upload.value = ()

    def load_bytes(self, name: str, content: bytes) -> None:
        """Read an uploaded file; ÄKTA exports and 2-column CSVs are used directly."""
        label = name.rsplit(".", 1)[0]
        self._roles_box.children = ()
        self._pending = None
        try:
            if is_akta_format(content):
                run = read_akta_csv(content, label)
                self._use_run(name, run, "ÄKTA/Unicorn export")
                return
            headers = read_headers(content)
            if len(headers) == 2:
                role = "time_s" if self._time_unit.value == "s" else "time_min"
                self._use_run(name, read_generic_csv(content, label, roles=[role, "signal"]),
                              "2-column CSV")
                return
        except ValueError as exc:
            self._run_note.value = status_html("error", f"Could not read {name}: {exc}")
            return
        if len(headers) < 2:
            self._run_note.value = status_html("error", f"Could not read {name}.")
            return
        self._pending = (name, content)
        self._role_dropdowns = [
            W.Dropdown(options=COLUMN_ROLE_OPTIONS, value=role, description=header)
            for header, role in zip(headers, detect_column_roles(headers))
        ]
        self._roles_box.children = (
            _note(f"Say what each column of {html.escape(name)} holds:"),
            *self._role_dropdowns,
            self._btn_roles,
        )
        self._run_note.value = ""

    def _apply_roles(self) -> None:
        if self._pending is None:
            return
        name, content = self._pending
        try:
            run = read_generic_csv(
                content, name.rsplit(".", 1)[0], roles=[d.value for d in self._role_dropdowns]
            )
        except ValueError as exc:
            self._run_note.value = status_html("error", str(exc))
            return
        self._roles_box.children = ()
        self._pending = None
        self._use_run(name, run, "CSV")

    def _use_run(self, data_file: str, run: ExperimentalRun, kind: str) -> None:
        self.uploaded[data_file] = run
        self.run, self.data_file = run, data_file
        self._run_note.value = status_html(
            "ok", f"{data_file}: {kind}, {len(run.channels)} channel(s) "
            f"({', '.join(run.channels)}), {run.x_basis} axis in {run.x_unit}, "
            f"{len(run.markers)} marker(s)."
        )

    def _on_pick_loaded(self, _change: dict) -> None:
        key = self._loaded.value
        if self._loading or key is None:
            return
        run = self._runs().get(key)
        if run is not None:
            self._use_run(key, run, "loaded run")
