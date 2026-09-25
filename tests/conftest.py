"""Shared fixtures."""
from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def cadet_process_descriptor_metadata():
    """Fail with a precise message when the imported CADET-Process predates PR #435.

    Column/binding/solver descriptors only carry `unit=`/`description=` from that PR on;
    a checkout without it (e.g. an older `dev`) makes the live-metadata tests fail with
    unrelated-looking assertion errors.
    """
    import CADETProcess
    from cadetgui.parameters import get_parameter

    meta = get_parameter("column", "GeneralRateModel", "length")
    if not meta.get("unit") or not meta.get("description"):
        pytest.fail(
            "The imported CADET-Process has no descriptor unit/description metadata "
            "(fau-advanced-separations/CADET-Process PR #435: commit 'Expose "
            "unit/description metadata on column, binding, and solver parameters'). "
            f"Imported from {CADETProcess.__file__}; check that checkout's branch/HEAD "
            "contains that commit.",
            pytrace=False,
        )
