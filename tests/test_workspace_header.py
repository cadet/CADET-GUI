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
    assert contains(header.root, config.persistence._btn_save)
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
    assert contains(config.root, config.persistence._btn_save)


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


def test_workbench_places_the_header_between_top_bar_and_sidebar():
    from cadetgui.widgets.composite import WorkbenchWidget

    wb = WorkbenchWidget()
    header = wb.configuration.workspace_header
    assert not wb.configuration.workspace_header_embedded
    assert wb.root.children[2] is header.root
    assert wb.root.children[3] is wb._shell.body
    assert not contains(wb.configuration.root, header.root)
    assert not contains(wb.configuration.root, header.persistence.root)


def test_workbench_without_process_configuration_has_no_header():
    from cadetgui.widgets.composite import WorkbenchWidget

    wb = WorkbenchWidget(include=("System Configuration", "Simulation"))
    assert wb.configuration is None
    assert len(wb.root.children) == 3


def test_workbench_leaves_an_embedded_configuration_header_alone():
    from cadetgui.widgets.composite import WorkbenchWidget

    config = ConfigurationWidget(instrument=InstrumentWidget())
    wb = WorkbenchWidget(configuration=config)
    assert contains(config.root, config.workspace_header.root)
    assert wb.root.children[2] is wb._shell.body
    assert len(wb.root.children) == 3


def test_workbench_simulation_follows_the_shared_headers_store_dir(tmp_path):
    from cadetgui.widgets.composite import WorkbenchWidget

    wb = WorkbenchWidget()
    other = tmp_path / "elsewhere"
    persistence = wb.configuration.workspace_header.persistence
    persistence._store_dir_field.value = str(other)
    persistence._btn_set_store_dir.click()
    expected = configuration_store.runs_dir(wb.configuration.config_name, store_dir=other)
    assert wb.solution.history.store_dir == expected


def test_characterization_workbench_places_the_same_header_above_the_sidebar():
    from cadetgui.widgets.composite import CharacterizationWorkbenchWidget

    wb = CharacterizationWorkbenchWidget()
    header = wb.configuration.workspace_header
    assert wb.root.children[2] is header.root
    assert wb.root.children[3] is wb._shell.body
    assert not contains(wb.configuration.root, header.root)
    wb.configuration.config_name = "Char config"
    assert wb.configuration.persist_to_store().exists()
    assert header.counts == (1, 0)


def test_characterization_workbench_with_configuration_given_keeps_its_own_header():
    from cadetgui.widgets.composite import CharacterizationWorkbenchWidget

    iw = InstrumentWidget()
    config = ConfigurationWidget(instrument=iw)
    wb = CharacterizationWorkbenchWidget(instrument=iw, configuration=config)
    assert contains(config.root, config.workspace_header.root)
    assert len(wb.root.children) == 3


def test_header_is_a_single_compact_row_with_the_persistence_widgets():
    config = ConfigurationWidget(instrument=InstrumentWidget())
    header = config.workspace_header
    persistence = config.persistence
    row, status, details = header.root.children
    assert "cadetgui-workspace-header" in header.root._dom_classes
    for widget in (
        persistence._name_field,
        persistence._btn_save,
        persistence._btn_toggle_save_load_details,
        header._summary,
        header.backend_versions.root,
    ):
        assert contains(row, widget)
    assert status is persistence.save_status
    assert details is persistence._save_load_details_box
    assert not contains(header.root, persistence.root)


def test_status_line_only_takes_space_when_non_empty():
    config = ConfigurationWidget(instrument=InstrumentWidget())
    status = config.persistence.save_status
    assert status.layout.display == "none"
    config.persistence._btn_save.click()
    assert status.layout.display == ""
    status.value = ""
    assert status.layout.display == "none"


def test_details_toggle_expands_below_the_row():
    config = ConfigurationWidget(instrument=InstrumentWidget())
    persistence = config.persistence
    details = config.workspace_header.root.children[2]
    assert details.layout.display == "none"
    persistence._btn_toggle_save_load_details.click()
    assert details.layout.display == ""
    assert persistence._btn_toggle_save_load_details.description == "Hide details"
