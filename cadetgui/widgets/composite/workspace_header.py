from __future__ import annotations

from pathlib import Path
from typing import Any

import ipywidgets as W

from ... import configuration_store
from .backend_versions import BackendVersionsWidget
from .configuration_persistence import ConfigurationPersistence

__all__ = ["WorkspaceHeader", "hoisted_header_rows"]


class WorkspaceHeader:
    """Panel answering "which configuration am I in, where is it saved, what runs on it".

    One compact row: the persistence panel's name field and Save button, a
    summary of the saved versions and runs of the current configuration, and on
    the right the `BackendVersionsWidget` and the details toggle (hash, storage
    folder and import expand below the row). Arranges the same widgets as
    `ConfigurationPersistence.root`, which is then not displayed.
    `refresh()` re-reads that summary; it runs on its own after every save,
    import, rename or folder change.
    """

    def __init__(self, persistence: ConfigurationPersistence) -> None:
        self.persistence = persistence
        self.backend_versions = BackendVersionsWidget()
        self._summary = W.HTML()
        self._summary.add_class("cadetgui-workspace-summary")
        parts = persistence.compact_parts()
        parts.toggle_button.add_class("cadetgui-workspace-toggle")
        parts.save_button.add_class("cadetgui-workspace-save")
        right = W.HBox(
            [parts.toggle_button, self.backend_versions.root],
            layout=W.Layout(margin="0 0 0 auto", align_items="center"),
        )
        row = W.HBox(
            [parts.name_field, parts.save_button, self._summary, right],
            layout=W.Layout(flex_flow="row wrap", align_items="center"),
        )
        row.add_class("cadetgui-workspace-row")
        self._status = parts.status
        self._sync_status_visibility()
        self._status.observe(self._sync_status_visibility, names="value")
        self.root = W.VBox([row, parts.status, parts.details])
        self.root.add_class("cadetgui-workspace-header")
        self.persistence.add_change_listener(self.refresh)
        self.refresh()

    def _sync_status_visibility(self, _change: Any = None) -> None:
        self._status.layout.display = "" if self._status.value else "none"

    def _folder(self) -> Path:
        store_dir = self.persistence.store_dir or configuration_store.default_store_dir()
        return store_dir / configuration_store.safe_config_dirname(self.persistence.config_name)

    @property
    def counts(self) -> tuple[int, int]:
        """(saved versions, runs) found in the current configuration's folder."""
        folder = self._folder()
        if not folder.is_dir():
            return 0, 0
        versions = len(list(folder.glob("config_*.h5")))
        runs = len(list((folder / "runs").glob("run_*.json"))) + len(
            list(folder.glob("run_*.json"))
        )
        return versions, runs

    def refresh(self) -> None:
        """Update the summary line from what is on disk now."""
        versions, runs = self.counts
        saved = (
            "Not saved yet"
            if versions == 0
            else f"{versions} saved version{'s' if versions != 1 else ''}"
        )
        self._summary.value = f"<span>{saved} · {runs} run{'s' if runs != 1 else ''}</span>"


def hoisted_header_rows(configuration: Any) -> list[W.Widget]:
    """Return `[header.root]` if `configuration` does not embed its header, else `[]`."""
    if configuration is None or configuration.workspace_header_embedded:
        return []
    return [configuration.workspace_header.root]
