from __future__ import annotations

import warnings

from cadetgui.characterization.guide import EXPERIMENT_TYPES
from cadetgui.io.configuration_store import ConfigurationState
from cadetgui.starting_values import (
    binding_starting_values,
    starting_values,
    with_starting_values,
)

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

SMA = "Steric Mass Action (SMA)"


def _recipe(**kwargs):
    values = dict(
        components=["Salt", "Protein"], column_key="Lumped Rate Model With Pores (LRMP)",
        binding_key=SMA, template_key="Load–Wash–Elute (LWE)",
        model_values={"c_buffer_a": [50.0, 0.0]},
    )
    values.update(kwargs)
    return ConfigurationState(**values)


def test_sma_starting_values_fill_zeros_and_keep_the_salt_at_zero():
    seeded = binding_starting_values(SMA, ["Salt", "Protein"], {
        "capacity": 0.0, "adsorption_rate": [0.0, 0.0], "is_kinetic": True,
    })
    start = starting_values()["binding"][SMA]
    assert seeded["capacity"] == start["scalar"]["capacity"]
    assert seeded["is_kinetic"] is start["scalar"]["is_kinetic"]
    assert seeded["reference_liquid_phase_conc"] == start["scalar"]["reference_liquid_phase_conc"]
    assert seeded["adsorption_rate"] == [0.0, start["per_component"]["adsorption_rate"]]
    assert seeded["steric_factor"] == [0.0, start["per_component"]["steric_factor"]]


def test_values_already_set_are_kept():
    seeded = binding_starting_values(SMA, ["Salt", "A", "B"], {
        "capacity": 800.0, "characteristic_charge": [0.0, 3.0, 0.0], "is_kinetic": True,
    })
    assert seeded["capacity"] == 800.0
    assert seeded["is_kinetic"] is True
    assert seeded["characteristic_charge"] == [0.0, 3.0, 4.7]


def test_models_without_starting_values_are_left_alone():
    values = {"adsorption_rate": [0.0], "desorption_rate": [0.0], "is_kinetic": True}
    assert binding_starting_values("Linear", ["A"], values) == values
    recipe = _recipe(binding_key="Linear", components=["A"])
    assert with_starting_values(recipe) is recipe


def test_method_values_follow_the_template_and_reset_the_column_start():
    seeded = with_starting_values(_recipe(column_values={"c": [10.0, 0.0]}))
    assert seeded.model_values["c_buffer_a"] == [50.0, 0.0]
    assert seeded.model_values["c_sample"] == [50.0, 1.0]
    assert seeded.column_values["c"] == seeded.column_values["cp"] == [50.0, 0.0]
    assert seeded.column_values["q"] == [1200.0, 0.0]
    assert seeded.show_optional_column

    pulse = with_starting_values(_recipe(template_key="Pulse Injection"))
    assert pulse.model_values["c_buffer_a"] == [400.0, 0.0]
    assert pulse.column_values["c"] == [400.0, 0.0]
    breakthrough = with_starting_values(_recipe(template_key="Breakthrough"))
    assert breakthrough.model_values["cycle_time"] == 1800.0


def test_without_method_only_the_binding_is_filled():
    recipe = _recipe(column_values={"c": [10.0, 0.0]})
    seeded = with_starting_values(recipe, method=False)
    assert seeded.model_values == recipe.model_values
    assert seeded.column_values == recipe.column_values
    assert seeded.binding_values["capacity"] == 1200.0

    unset = with_starting_values(_recipe(), method=False)
    assert unset.model_values == {"c_buffer_a": [50.0, 0.0]}
    assert unset.column_values["c"] == [50.0, 0.0]
    assert with_starting_values(_recipe(), method=False, equilibrate=False).column_values == {}


def test_every_listed_method_names_real_template_fields():
    from types import SimpleNamespace

    from cadetgui.cadetprocessadapter import INSTRUMENT_TEMPLATES
    from CADETProcess.processModel import ComponentSystem

    stub = SimpleNamespace(component_system=ComponentSystem(["Salt", "Protein"]))
    for entry in starting_values()["binding"].values():
        for template, method in entry.get("methods", {}).items():
            fields = {f.name for f in INSTRUMENT_TEMPLATES[template](stub).fields}
            assert set(method) - {"note"} <= fields, template


def test_binding_experiment_types_get_starting_values():
    base = _recipe(binding_key="None", components=["Salt"], model_values={})
    recipe = EXPERIMENT_TYPES["linear_gradient_elution"].apply(base, component="Lysozyme")
    assert recipe.binding_values["capacity"] > 0
    assert recipe.binding_values["characteristic_charge"][1] > 0


def test_configuration_fills_starting_values_into_a_fresh_sma_setup(tmp_path, monkeypatch):
    import cadetgui.io.configuration_store as configuration_store
    from cadetgui.widgets.composite import ConfigurationWidget, InstrumentWidget

    monkeypatch.setattr(configuration_store, "default_store_dir", lambda: tmp_path)

    cw = ConfigurationWidget(instrument=InstrumentWidget())
    cw.components = ["Salt", "Protein"]
    assert all(v == 0 for v in cw.binding_form.collect_values()["adsorption_rate"])

    cw.select_models(template="Load–Wash–Elute (LWE)", binding=SMA)
    state = cw.snapshot()
    assert state.binding_values["capacity"] == 1200.0
    assert state.binding_values["adsorption_rate"] == [0.0, 8.0]
    assert state.binding_values["reference_liquid_phase_conc"] == 1000.0
    assert state.show_optional_binding
    assert state.model_values["c_buffer_a"] == [50.0, 0.0]
    assert state.column_values["c"] == [50.0, 0.0]
    assert "cp" not in state.column_values

    cw.select_models(template="Pulse Injection")
    assert cw.snapshot().model_values["c_buffer_a"] == [400.0, 0.0]


def test_optional_binding_values_replace_defaults_only_on_an_untouched_model():
    defaults = {"adsorption_rate": [0.0, 0.0], "reference_liquid_phase_conc": 1.0}
    assert binding_starting_values(SMA, ["Salt", "Protein"], defaults)[
        "reference_liquid_phase_conc"] == 1000.0
    edited = {"adsorption_rate": [0.0, 2.0], "reference_liquid_phase_conc": 1.0}
    assert binding_starting_values(SMA, ["Salt", "Protein"], edited)[
        "reference_liquid_phase_conc"] == 1.0


def test_starting_values_can_be_switched_off(tmp_path, monkeypatch):
    import cadetgui.io.configuration_store as configuration_store
    from cadetgui.widgets.composite import ConfigurationWidget, InstrumentWidget

    monkeypatch.setattr(configuration_store, "default_store_dir", lambda: tmp_path)

    cw = ConfigurationWidget(instrument=InstrumentWidget(), starting_values=False)
    cw.components = ["Salt", "Protein"]
    cw.select_models(template="Load–Wash–Elute (LWE)", binding=SMA)
    assert cw.snapshot().binding_values["capacity"] == 0.0

    cw.use_starting_values = True
    state = cw.snapshot()
    assert state.binding_values["capacity"] == 1200.0
    assert state.model_values["c_buffer_a"] == [50.0, 0.0]

    cw.use_starting_values = False
    cw.select_models(template="Pulse Injection")
    assert cw.snapshot().model_values["c_buffer_a"] != [400.0, 0.0]


def test_workbench_passes_the_starting_values_switch_on(tmp_path, monkeypatch):
    import cadetgui.io.configuration_store as configuration_store
    from cadetgui.widgets.composite import WorkbenchWidget

    monkeypatch.setattr(configuration_store, "default_store_dir", lambda: tmp_path)

    steps = ["System", "Process configuration"]
    assert WorkbenchWidget(include=steps).configuration.use_starting_values
    off = WorkbenchWidget(include=steps, starting_values=False)
    assert not off.configuration.use_starting_values
