from __future__ import annotations

from typing import Callable, List, Optional

import ipywidgets as W

from ...io.experimental_data import (
    ColumnRole,
    ExperimentalDataset,
    ExperimentalRun,
    detect_column_roles,
    is_akta_format,
    read_akta_csv,
    read_generic_csv,
    read_headers,
    to_time,
)
from .._chrome import style_tag
from .._status import status_html
from ..elements import ChoiceField
from ._measurement_common import COLUMN_ROLE_OPTIONS

__all__ = ["DataImportWidget", "ExperimentalDataset"]


class DataImportWidget:
    """Import experimental chromatography data for comparison.

    Reads generic header CSVs (one x column + N signal columns) and Äkta/Unicorn-style
    exports (auto-detected). A simple 2-column CSV is auto-mapped using the min/s
    toggle, same as before; anything else gets a column-mapping step before import.
    """

    def __init__(self) -> None:
        self.datasets: List[ExperimentalDataset] = []
        self._listeners: List[Callable[[], None]] = []

        self._upload = W.FileUpload(
            accept=".csv,.txt,.tsv", multiple=True, description="Import CSV"
        )
        self._time_unit = ChoiceField(
            label="Time column is in:",
            options=[("minutes", "min"), ("seconds", "s")],
        )
        self._dataset_picker = ChoiceField(label="Loaded:", options=[])
        self._btn_remove = W.Button(description="Remove", icon="trash")
        self._mapping_box = W.VBox([])
        self._basis_label = W.HTML()
        self._preview_out = W.Output()
        self.status = W.HTML("<em>No experimental data loaded.</em>")
        self.status.add_class("cadetgui-status")

        self._upload.observe(self._on_upload, names="value")
        self._btn_remove.on_click(self._on_remove)
        self._dataset_picker.observe(self._on_pick, names="selected_index")

        toolbar = W.HBox(
            [self._upload, self._time_unit, self._dataset_picker, self._btn_remove],
            layout=W.Layout(flex_flow="row wrap"),
        )
        toolbar.add_class("cadetgui-toolbar")

        self.root = W.VBox(
            [
                W.HTML(style_tag()),
                toolbar,
                self._mapping_box,
                self._basis_label,
                self._preview_out,
                self.status,
            ]
        )
        self.root.add_class("cadetgui-panel")

    def add_listener(self, fn: Callable[[], None]) -> None:
        """Register a callback fired (no args) whenever the dataset list changes."""
        self._listeners.append(fn)

    def _notify(self) -> None:
        for fn in list(self._listeners):
            fn()

    def _on_upload(self, _change: dict) -> None:
        if not self._upload.value:
            return
        for item in self._upload.value:
            self._handle_upload_item(item)
        self._upload.value = ()  # allow re-uploading the same filename later
        self._finish_import()

    def _handle_upload_item(self, item: dict) -> None:
        name = item["name"]
        label = name.rsplit(".", 1)[0]
        content = bytes(item["content"])

        if is_akta_format(content):
            self._queue_mapping(label, name, content, akta=True)
            return

        headers = read_headers(content)
        if len(headers) == 2:
            self._import_simple(label, name, content)
        elif len(headers) > 2:
            self._queue_mapping(label, name, content, akta=False, headers=headers)
        else:
            self.status.value = status_html("error", f"Could not parse {name}.")

    def _import_simple(self, label: str, name: str, content: bytes) -> None:
        """Auto-map a plain 2-column CSV using the min/s toggle, no mapping step."""
        role: ColumnRole = "time_s" if self._time_unit.value == "s" else "time_min"
        try:
            run = read_generic_csv(content, label, roles=[role, "signal"])
        except ValueError:
            self.status.value = status_html("error", f"Could not parse {name}.")
            return
        channel_name = next(iter(run.channels))
        if run.channels[channel_name].x.size == 0:
            self.status.value = status_html("error", f"Could not parse {name}.")
            return
        self._add_dataset_from_channel(run, channel_name)

    def _queue_mapping(
        self,
        label: str,
        name: str,
        content: bytes,
        *,
        akta: bool,
        headers: Optional[List[str]] = None,
    ) -> None:
        role_dropdowns: List[W.Dropdown] = []
        parsed_run: Optional[ExperimentalRun] = None

        if akta:
            try:
                parsed_run = read_akta_csv(content, label)
            except ValueError:
                self.status.value = status_html("error", f"Could not parse {name}.")
                return
        else:
            default_roles = detect_column_roles(headers or [])
            role_dropdowns = [
                W.Dropdown(options=COLUMN_ROLE_OPTIONS, value=role, description=header)
                for header, role in zip(headers or [], default_roles)
            ]

        flow_rate_field = W.FloatText(value=1.0, description="Flow rate (mL/min):")
        flow_rate_box = W.HBox([flow_rate_field])

        def _update_flow_visibility(_change: object = None) -> None:
            is_volume = akta or any(d.value == "volume_ml" for d in role_dropdowns)
            flow_rate_box.layout.display = "" if is_volume else "none"

        for dropdown in role_dropdowns:
            dropdown.observe(_update_flow_visibility, names="value")
        _update_flow_visibility()

        import_btn = W.Button(description="Import", button_style="primary")
        cancel_btn = W.Button(description="Cancel")

        def _remove_panel() -> None:
            self._mapping_box.children = tuple(
                c for c in self._mapping_box.children if c is not panel
            )

        def _on_import(_btn: object) -> None:
            if akta:
                built = parsed_run
            else:
                roles = [d.value for d in role_dropdowns]
                try:
                    built = read_generic_csv(content, label, roles=roles)
                except ValueError as exc:
                    self.status.value = status_html("error", str(exc))
                    return
            flow_rate = (
                flow_rate_field.value * 1e-6 / 60.0 if built.x_basis == "volume" else None
            )
            for channel_name in built.channels:
                self._add_dataset_from_channel(built, channel_name, flow_rate)
            _remove_panel()
            self._finish_import()

        def _on_cancel(_btn: object) -> None:
            _remove_panel()

        import_btn.on_click(_on_import)
        cancel_btn.on_click(_on_cancel)

        rows: List[W.Widget] = [W.HTML(f"<b>Map columns — {name}</b>")]
        if akta:
            channel_list = ", ".join(parsed_run.channels)
            rows.append(W.HTML(f"Detected Äkta/Unicorn export. Channels: {channel_list}."))
        else:
            rows.extend(role_dropdowns)
        rows.append(flow_rate_box)
        rows.append(W.HBox([import_btn, cancel_btn]))
        panel = W.VBox(rows)
        panel.add_class("cadetgui-panel")
        self._mapping_box.children = tuple(self._mapping_box.children) + (panel,)

    def _add_dataset_from_channel(
        self, run: ExperimentalRun, channel_name: str, flow_rate: Optional[float] = None
    ) -> None:
        time_s, values = to_time(run, channel_name, flow_rate)
        label = run.label if len(run.channels) == 1 else f"{run.label} — {channel_name}"
        ds = ExperimentalDataset(
            label=label, time_min=time_s / 60.0, signal=values, run=run, channel=channel_name
        )
        self.datasets.append(ds)
        self.status.value = f"<em>Loaded {label} ({time_s.size} points).</em>"

    def _finish_import(self) -> None:
        self._dataset_picker.set_options([(d.label, d) for d in self.datasets], keep_value=False)
        if self.datasets:
            self._dataset_picker.selected_index = len(self.datasets) - 1
        self._preview_selected()
        self._notify()

    def _on_remove(self, _btn: object) -> None:
        ds = self._dataset_picker.value
        if ds is None:
            return
        self.datasets.remove(ds)
        self._dataset_picker.set_options([(d.label, d) for d in self.datasets])
        self._preview_out.clear_output()
        self._basis_label.value = ""
        self.status.value = f"<em>Removed {ds.label}.</em>"
        self._notify()

    def _on_pick(self, _change: dict) -> None:
        self._preview_selected()

    def _preview_selected(self) -> None:
        ds: Optional[ExperimentalDataset] = self._dataset_picker.value
        self._preview_out.clear_output(wait=True)
        if ds is None:
            self._basis_label.value = ""
            return
        self._basis_label.value = f"<em>x-basis: {ds.run.x_basis if ds.run else 'time'}</em>"
        with self._preview_out:
            import matplotlib.pyplot as plt
            from IPython.display import display

            fig, ax = plt.subplots(figsize=(5, 3))
            ax.plot(ds.time_min, ds.signal)
            ax.set_xlabel("Time / min")
            ax.set_ylabel("Signal")
            ax.set_title(ds.label)
            display(fig)
            plt.close(fig)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
