from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

import ipywidgets as W

from ...configuration_store import (
    ConfigurationState,
    compute_hash,
    load_from_store,
    load_h5,
    save_to_store,
)
from .._settings_popover import toggle_box
from ..elements import TextField

__all__ = ["ConfigurationPersistence"]


class ConfigurationPersistence:
    """Save/import-to-store panel for one `ConfigurationWidget`.

    Owns the name/hash/storage-folder UI and the actual save/import calls;
    knows nothing about columns, binding models, or forms -- it reaches the
    rest of the configuration only through the `snapshot`/`apply_state`/
    `get_process` callbacks handed in by its owner.
    """

    def __init__(
        self,
        *,
        default_name: str,
        snapshot: Callable[[], ConfigurationState],
        apply_state: Callable[[str, ConfigurationState], None],
        get_process: Callable[[], Any],
        on_name_change: Callable[[str], None],
    ) -> None:
        self._snapshot = snapshot
        self._apply_state = apply_state
        self._get_process = get_process
        self._on_name_change_cb = on_name_change
        self.config_name: str = default_name
        self.store_dir: Optional[Path] = None

        # Always-visible row: name field + Save/Show-details buttons.
        self._name_field = TextField(label="Configuration name:", value=default_name)
        self._btn_save = W.Button(description="Save", icon="save")
        self._btn_toggle_save_load_details = W.Button(
            description="Show details", icon="chevron-down"
        )
        self.save_status = W.HTML()
        self.save_status.add_class("cadetgui-status")

        # Collapsed by default under "Show details": hash + storage folder + import.
        self._hash_display = W.HTML("<em>No configuration built yet.</em>")
        self._store_dir_field = TextField(label="Storage folder:", value="")
        self._btn_set_store_dir = W.Button(description="Set folder", icon="folder-open")
        self._store_dir_note = W.HTML(
            "<em>Leave blank to use the default (~/.cadetgui/configurations).</em>"
        )
        self._store_dir_note.add_class("cadetgui-note")
        self._file_upload = W.FileUpload(description="Import file", accept=".h5", multiple=False)
        self._import_hash_field = TextField(label="Import by hash:", value="")
        self._btn_import_hash = W.Button(description="Import", icon="download")
        self._save_load_details_box = W.VBox(
            [
                self._hash_display,
                W.HTML("<hr>"),
                W.HBox([self._store_dir_field, self._btn_set_store_dir]),
                self._store_dir_note,
                W.HTML("<hr>"),
                self._file_upload,
                W.HBox([self._import_hash_field, self._btn_import_hash]),
            ],
            layout=W.Layout(display="none"),
        )
        self.root = W.VBox(
            [
                W.HTML("<div class='cadetgui-section-title'>Save / Load Configuration</div>"),
                self._name_field,
                W.HBox([self._btn_save, self._btn_toggle_save_load_details]),
                self.save_status,
                self._save_load_details_box,
            ]
        )
        self.root.add_class("cadetgui-section")

        self._name_field.observe(self._on_name_change, names="value")
        self._btn_set_store_dir.on_click(self._on_set_store_dir)
        self._btn_save.on_click(self._on_save)
        self._file_upload.observe(self._on_file_upload_change, names="value")
        self._btn_import_hash.on_click(self._on_import_hash_click)
        self._btn_toggle_save_load_details.on_click(self._on_toggle_save_load_details)

    @property
    def config_hash(self) -> Optional[str]:
        """Content hash of the current configuration, or None if nothing is built yet."""
        try:
            return compute_hash(self._snapshot())
        except RuntimeError:
            return None

    def refresh_hash_display(self) -> None:
        """Update the hash line to match the current `config_hash`."""
        if self.config_hash is None:
            self._hash_display.value = "<em>No configuration built yet.</em>"
        else:
            self._hash_display.value = f"<strong>Hash:</strong> <code>{self.config_hash}</code>"

    def set_name(self, name: str) -> None:
        """Rename after restoring a saved configuration, and refresh the hash display."""
        self.config_name = name
        self._name_field.value = name
        self.refresh_hash_display()

    def name_error(self, action: str = "saving") -> Optional[str]:
        """Error message if this configuration has no name yet for `action`, else None."""
        if self.config_name.strip():
            return None
        return f"Give the configuration a name before {action}."

    def persist_to_store(self) -> Path:
        """Snapshot and save the current configuration to the store. Returns its path.

        Raises RuntimeError if unnamed or nothing has been built yet.
        """
        error = self.name_error()
        if error:
            raise RuntimeError(error)
        state = self._snapshot()
        return save_to_store(
            state, self.config_name, process=self._get_process(), store_dir=self.store_dir
        )

    def import_from_store(self, hash_: str) -> None:
        """Load a configuration previously saved to the local store, by its hash."""
        try:
            name, state = load_from_store(hash_, store_dir=self.store_dir)
            self._apply_state(name, state)
        except Exception as exc:  # noqa: BLE001
            self.save_status.value = f"<span style='color:#b00020'>{exc}</span>"
            return
        self.save_status.value = f"<em>Imported '{name}' ({hash_}).</em>"

    def _on_name_change(self, change: dict) -> None:
        if change.get("name") != "value":
            return
        self.config_name = change["new"]
        self._on_name_change_cb(self.config_name)

    def _on_set_store_dir(self, _btn: Any) -> None:
        text = self._store_dir_field.value.strip()
        if not text:
            self.store_dir = None
            self.save_status.value = "<em>Using the default storage folder.</em>"
            return
        try:
            path = Path(text).expanduser().resolve()
            path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            self.save_status.value = f"<span style='color:#b00020'>{exc}</span>"
            return
        self.store_dir = path
        self._store_dir_field.value = str(path)
        self.save_status.value = f"<em>Configurations will be saved to {path}.</em>"

    def _on_save(self, _btn: Any) -> None:
        try:
            path = self.persist_to_store()
        except Exception as exc:  # noqa: BLE001
            self.save_status.value = f"<span style='color:#b00020'>{exc}</span>"
            return
        self.refresh_hash_display()
        self.save_status.value = f"<em>Saved to {path}.</em>"

    def _on_file_upload_change(self, change: dict) -> None:
        if change.get("name") != "value" or not self._file_upload.value:
            return
        item = self._file_upload.value[0]
        try:
            import tempfile

            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir) / item["name"]
                tmp_path.write_bytes(bytes(item["content"]))
                name, state = load_h5(tmp_path)
            self._apply_state(name, state)
        except Exception as exc:  # noqa: BLE001
            self.save_status.value = f"<span style='color:#b00020'>{exc}</span>"
            return
        finally:
            self._file_upload.value = ()
        self.save_status.value = f"<em>Imported '{name}' from {item['name']}.</em>"

    def _on_import_hash_click(self, _btn: Any) -> None:
        self.import_from_store(self._import_hash_field.value.strip())

    def _on_toggle_save_load_details(self, _btn: Any) -> None:
        shown = toggle_box(self._save_load_details_box)
        self._btn_toggle_save_load_details.description = "Hide details" if shown else "Show details"
