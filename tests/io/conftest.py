"""Fixtures for the store and data-file tests."""

from __future__ import annotations

import pytest
from cadetgui.io.configuration_store import ConfigurationState, InstrumentState

DEFAULT = object()


@pytest.fixture
def make_state():
    """Build a ConfigurationState with every field set; keyword arguments override."""

    def make(*, instrument=DEFAULT, **overrides) -> ConfigurationState:
        if instrument is DEFAULT:
            instrument = InstrumentState(
                include_sample_loop=True,
                sample_loop_volume=50e-9,
                sample_loop_diameter_auto=True,
                sample_loop_diameter=0.75e-3,
                bypass_units=["tubing_post_column"],
                unit_values={
                    "mixer": {"init_liquid_volume": 2.5e-5},
                    "tubing_pre_column": {"length": 0.33, "axial_dispersion": 2e-8},
                },
            )
        fields = dict(
            components=["Salt", "Protein"],
            column_key="Lumped Rate Model Without Pores (LRM)",
            binding_key="Linear",
            template_key="Load–Wash–Elute (LWE)",
            instrument=instrument,
            multiplex_state={"axial_dispersion": False},
            show_optional_column=False,
            show_optional_binding=True,
            column_values={"length": 0.5, "diameter": 0.024},
            binding_values={"is_kinetic": True, "adsorption_rate": [0.0, 1.5]},
            model_values={"flow_rate": 1e-6, "cycle_time": 6000.0},
        )
        fields.update(overrides)
        return ConfigurationState(**fields)

    return make
