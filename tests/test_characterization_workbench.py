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


def test_builds_all_nine_panes_by_default():
    wb = CharacterizationWorkbenchWidget()

    assert list(wb._nav.options) == [
        "System", "Configuration",
        "Periphery: pre-injection", "Periphery: detectors", "Periphery: pre-injection + mixer",
        "Bed", "Particles", "Adsorption", "Capacity",
    ]
    assert wb._nav.index == 0


def test_default_instrument_and_configuration_are_seeded_for_every_stage_to_work():
    wb = CharacterizationWorkbenchWidget()

    # LC system + the periphery units are needed for the two "Periphery: ..."
    # panes to have anything to fit against.
    assert wb.instrument.enabled
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
    for name in list(wb._nav.options)[1:]:
        assert wb._shell.panes[name].layout.display == "none"


def test_nav_switches_the_visible_pane():
    wb = CharacterizationWorkbenchWidget()

    wb._nav.index = 5  # "Bed"

    assert wb._shell.panes["Bed"].layout.display == ""
    assert wb._shell.panes["System"].layout.display == "none"


def test_include_narrows_which_panes_are_built_and_shown():
    wb = CharacterizationWorkbenchWidget(include=("System", "Configuration", "Bed"))

    assert list(wb._nav.options) == ["System", "Configuration", "Bed"]
    assert set(wb._stages) == {"Bed"}
    # System/Configuration objects always exist -- every stage needs them,
    # even one whose own pane isn't shown.
    assert wb.instrument is not None
    assert wb.configuration is not None


def test_include_rejects_unknown_step():
    with pytest.raises(ValueError):
        CharacterizationWorkbenchWidget(include=("System", "Not A Step"))


def test_accepts_prebuilt_instrument_and_configuration_unmodified():
    iw = InstrumentWidget()
    cw = ConfigurationWidget(instrument=iw)
    assert not iw.enabled  # left at its own default -- not seeded like the auto-built case

    wb = CharacterizationWorkbenchWidget(instrument=iw, configuration=cw)

    assert wb.instrument is iw
    assert wb.configuration is cw
    assert not wb.instrument.enabled  # untouched, unlike the default-constructed case
