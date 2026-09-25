from __future__ import annotations

import warnings

import matplotlib
import pytest

matplotlib.use("Agg")

import cadetgui.configuration_store as configuration_store
from cadetgui.widgets.composite import (
    ConfigurationWidget,
    InstrumentWidget,
    WorkspaceHeader,
)

warnings.filterwarnings("ignore", category=UserWarning)


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(configuration_store, "default_store_dir", lambda: tmp_path)


def contains(root, target) -> bool:
    if root is target:
        return True
    return any(contains(child, target) for child in getattr(root, "children", ()))


def summary_text(header: WorkspaceHeader) -> str:
    return header._summary.value


def test_header_composes_the_persistence_panel():
    config = ConfigurationWidget(instrument=InstrumentWidget())
    header = config.workspace_header
    assert isinstance(header, WorkspaceHeader)
    assert header.persistence is config.persistence
    assert contains(header.root, config.persistence.root)
    assert contains(header.root, header.backend_versions.root)


def test_summary_counts_follow_save_and_runs(tmp_path):
    config = ConfigurationWidget(instrument=InstrumentWidget())
    header = config.workspace_header
    assert header.counts == (0, 0)
    assert "Not saved yet" in summary_text(header)

    config.persistence._btn_save.click()
    assert header.counts == (1, 0)
    assert "1 saved version " in summary_text(header)

    runs = configuration_store.runs_dir(config.config_name)
    (runs / "run_a.json").write_text("{}")
    (runs / "run_a.h5").write_text("")
    header.refresh()
    assert header.counts == (1, 1)
    assert "1 run" in summary_text(header)


def test_rename_switches_to_the_new_configurations_folder():
    config = ConfigurationWidget(instrument=InstrumentWidget())
    header = config.workspace_header
    config.persistence._btn_save.click()
    assert header.counts[0] == 1
    config.persistence._name_field.value = "Another name"
    assert header.counts == (0, 0)
    assert "Not saved yet" in summary_text(header)


def test_summary_does_not_create_folders(tmp_path):
    config = ConfigurationWidget(instrument=InstrumentWidget())
    config.persistence._name_field.value = "Never saved"
    assert not (tmp_path / "Never_saved").exists()


def test_store_dir_change_is_followed(tmp_path):
    config = ConfigurationWidget(instrument=InstrumentWidget())
    header = config.workspace_header
    config.persistence._btn_save.click()
    other = tmp_path / "elsewhere"
    config.persistence._store_dir_field.value = str(other)
    config.persistence._btn_set_store_dir.click()
    assert header.counts == (0, 0)


def test_standalone_configuration_embeds_the_header_by_default():
    config = ConfigurationWidget(instrument=InstrumentWidget())
    assert contains(config.root, config.workspace_header.root)
    assert contains(config.root, config.persistence.root)


def test_workspace_header_false_keeps_it_out_of_the_root():
    config = ConfigurationWidget(instrument=InstrumentWidget(), workspace_header=False)
    assert not contains(config.root, config.workspace_header.root)
    assert not contains(config.root, config.persistence.root)
    config.config_name = "Still works"
    assert config.persist_to_store().exists()


def test_run_count_refreshes_after_a_run_and_a_failed_run():
    from cadetgui.widgets.composite import SolutionWidget

    config = ConfigurationWidget(instrument=InstrumentWidget())
    outcomes = iter([RuntimeError("boom"), None])

    def runner(process, **kwargs):
        outcome = next(outcomes)
        if outcome is not None:
            raise outcome
        return object()

    solution = SolutionWidget(runner=runner)
    solution.bind_to_config(config)
    solution._load_result = lambda result: None
    solution._on_run(None)
    assert config.workspace_header.counts[1] == 1
    solution._on_run(None)
    assert config.workspace_header.counts[1] == 2
