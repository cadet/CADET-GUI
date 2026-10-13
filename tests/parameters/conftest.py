"""Fixtures for the parameter metadata and spec tests."""

from __future__ import annotations

import pytest
from CADETProcess.processModel import ComponentSystem


@pytest.fixture
def component_system():
    """Two components, so per-component fields are distinguishable from scalars."""
    return ComponentSystem(["Salt", "Protein"])
