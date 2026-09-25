from __future__ import annotations

import warnings

import cadetgui.configuration_store as configuration_store
import pytest
from cadetgui.widgets.composite import (
    CharacterizationWorkbenchWidget,
    ConfigurationWidget,
    InstrumentWidget,
)

warnings.filterwarnings("ignore", category=UserWarning)


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Redirect the configuration store to a tmp dir -- never touch the real one."""
    monkeypatch.setattr(configuration_store, "default_store_dir", lambda: tmp_path)


def test_builds_all_ten_panes_by_default():
    wb = CharacterizationWorkbenchWidget()

    assert list(wb._shell.panes) == [
        "System Configuration", "Process Configuration",
        "Periphery: pre-injection", "Periphery: detectors", "Periphery: pre-injection + mixer",
        "Bed", "Particles", "Adsorption", "Capacity", "History",
    ]
    assert wb._nav.index == 0


def test_periphery_is_one_collapsible_sidebar_entry():
    wb = CharacterizationWorkbenchWidget()

    assert [key for _, key in wb._nav.options] == [
        "System Configuration", "Process Configuration", "Periphery",
        "Bed", "Particles", "Adsorption", "Capacity", "History",
    ]

    wb._nav.value = "Periphery"

    assert [label for label, _ in wb._nav.options][2:6] == [
        "\u25be Periphery", "pre-injection", "detectors", "pre-injection + mixer",
    ]
    assert wb._nav.value == "System Configuration"


def test_default_instrument_and_configuration_are_seeded_for_every_stage_to_work():
    wb = CharacterizationWorkbenchWidget()

    # The periphery units are needed for the two "Periphery: ..." panes to
    # have anything to fit against.
    for unit in ("tubing_pre_injection", "tubing_detectors", "mixer"):
        assert unit not in wb.instrument.bypass_units()

    # A column with pores + a binding model with capacity/characteristic
    # charge -- the bare LRM/Linear default has neither.
    column = wb.configuration.process.flow_sheet.column
    assert hasattr(column, "bed_porosity")
    assert hasattr(column.binding_model, "capacity")
    assert hasattr(column.binding_model, "characteristic_charge")


def test_stage_widgets_share_the_same_configuration_and_instrument():
    wb = CharacterizationWorkbenchWidget()

    for name in (
        "Periphery: pre-injection", "Periphery: detectors", "Periphery: pre-injection + mixer",
        "Bed", "Particles", "Adsorption", "Capacity",
    ):
        stage = wb._stages[name]
        assert stage._config is wb.configuration
    assert wb._stages["Periphery: pre-injection"]._instrument is wb.instrument
    assert wb._stages["Bed"]._instrument is None  # doesn't write back to the instrument


def test_only_the_first_pane_is_visible_initially():
    wb = CharacterizationWorkbenchWidget()

    assert wb.instrument.root.layout.display == ""
    for name in list(wb._shell.panes)[1:]:
        assert wb._shell.panes[name].layout.display == "none"


def test_nav_switches_the_visible_pane():
    wb = CharacterizationWorkbenchWidget()

    wb._shell.show("Bed")

    assert wb._shell.panes["Bed"].layout.display == ""
    assert wb._shell.panes["System Configuration"].layout.display == "none"


def test_include_narrows_which_panes_are_built_and_shown():
    steps = ("System Configuration", "Process Configuration", "Bed")
    wb = CharacterizationWorkbenchWidget(include=steps)

    assert list(wb._nav.options) == ["System Configuration", "Process Configuration", "Bed"]
    assert set(wb._stages) == {"Bed"}
    # System/Configuration objects always exist -- every stage needs them,
    # even one whose own pane isn't shown.
    assert wb.instrument is not None
    assert wb.configuration is not None


def test_include_rejects_unknown_step():
    with pytest.raises(ValueError):
        CharacterizationWorkbenchWidget(include=("System Configuration", "Not A Step"))


def test_every_stage_shares_the_same_history():
    wb = CharacterizationWorkbenchWidget()

    for stage in wb._stages.values():
        assert stage.history is wb.history


def test_reapply_routes_to_the_stage_whose_write_targets_match():
    wb = CharacterizationWorkbenchWidget()

    push = wb.history.record(
        "bed", {"bed_porosity": 0.5, "axial_dispersion": 3e-7},
    )
    before = wb._stages["Particles"]._config.process.flow_sheet.column.bed_porosity

    wb.history._on_reapply_click(None)  # "Re-apply" on the just-recorded push

    after = wb.configuration.process.flow_sheet.column.bed_porosity
    assert after == pytest.approx(0.5)
    assert after != before


def test_reapply_disambiguates_between_the_two_periphery_panes():
    wb = CharacterizationWorkbenchWidget()

    push = wb.history.record("periphery", {"tubing_detectors_length": 1.5})
    wb.history._picker.selected_index = list(wb.history.pushes).index(push)

    wb.history._on_reapply_click(None)

    detectors_form = wb.instrument._unit_forms["tubing_detectors"]
    pre_injection_form = wb.instrument._unit_forms["tubing_pre_injection"]
    assert detectors_form.collect_values()["length"] == pytest.approx(1.5)
    assert pre_injection_form.collect_values()["length"] != pytest.approx(1.5)


def test_accepts_prebuilt_instrument_and_configuration_unmodified():
    iw = InstrumentWidget()
    cw = ConfigurationWidget(instrument=iw)
    assert "mixer" in iw.bypass_units()  # not seeded like the auto-built case

    wb = CharacterizationWorkbenchWidget(instrument=iw, configuration=cw)

    assert wb.instrument is iw
    assert wb.configuration is cw
    assert "mixer" in wb.instrument.bypass_units()  # untouched, unlike the default-constructed case


def _warned(wb):
    keys = [o[1] if isinstance(o, tuple) else o for o in wb._nav.options]
    return {key for key, tip in zip(keys, wb._nav.tooltips) if tip}


def test_collapsed_periphery_group_shows_its_childrens_warning():
    wb = CharacterizationWorkbenchWidget(include=("System Configuration", "Periphery: detectors"))

    assert _warned(wb) == {"Periphery"}

    wb._shell.show("Periphery: detectors")

    assert _warned(wb) == {"Periphery: detectors"}


def test_stage_panes_are_flagged_until_they_have_a_dataset():
    import numpy as np
    from cadetgui.widgets.composite.data_import import ExperimentalDataset

    steps = ("System Configuration", "Process Configuration", "Bed", "Capacity")
    wb = CharacterizationWorkbenchWidget(include=steps)
    warned = _warned(wb)
    assert warned == {"Bed", "Capacity"}

    bed = wb._stages["Bed"]
    bed.data.datasets.append(ExperimentalDataset("d", np.array([0.0, 1.0]), np.array([0.0, 1.0])))
    bed.data._notify()

    warned = _warned(wb)
    assert warned == {"Capacity"}
