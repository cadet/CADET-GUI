from __future__ import annotations

from pathlib import Path

import ipywidgets as W

from ... import configuration_store
from .backend_versions import BackendVersionsWidget
from .configuration_persistence import ConfigurationPersistence

__all__ = ["WorkspaceHeader"]


class WorkspaceHeader:
    """Panel answering "which configuration am I in, where is it saved, what runs on it".

    Composes a `ConfigurationPersistence` (name, Save, and under "Show details"
    the hash/storage folder/import) with a `BackendVersionsWidget` and a one-line
    summary of the saved versions and runs of the current configuration.
    `refresh()` re-reads that summary; it runs on its own after every save,
    import, rename or folder change.
    """

    def __init__(self, persistence: ConfigurationPersistence) -> None:
        self.persistence = persistence
        self.backend_versions = BackendVersionsWidget()
        self._summary = W.HTML()
        self._summary.add_class("cadetgui-workspace-summary")
        footer = W.HBox(
            [self._summary, self.backend_versions.root],
            layout=W.Layout(justify_content="space-between", flex_flow="row wrap"),
        )
        self.root = W.VBox([self.persistence.root, footer])
        self.persistence.add_change_listener(self.refresh)
        self.refresh()

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
