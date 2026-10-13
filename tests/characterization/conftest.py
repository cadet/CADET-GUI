"""Characterization fixtures: the synthetic example study and its first accepted step."""
from __future__ import annotations

import pytest
from cadetgui.characterization.parameter_store import Provenance
from cadetgui.characterization.study import Study

from characterization.synthetic import DISPERSION, LENGTH, MANIFEST


@pytest.fixture
def study() -> Study:
    """The synthetic Äkta-style example study: Extra-column volume, then Column packing."""
    return Study.load(MANIFEST)


def first_step_posterior(study: Study):
    """A posterior of the example's first step, built on the current initial store."""
    return study.initial_store.updated(
        {LENGTH: 0.42, DISPERSION: {"SystemTracer": 4.5e-7}},
        Provenance(
            step="Extra-column volume", probe="SystemTracer",
            source="System pulse 1 (UV), System pulse 2 (UV)",
            metric={"System pulse 1 (UV)_NRMSE": 0.01, "System pulse 2 (UV)_NRMSE": 0.02},
        ),
    )


@pytest.fixture
def periphery_posterior(study):
    """A posterior of the example's first step (not accepted)."""
    return first_step_posterior(study)


@pytest.fixture
def accept_periphery(study):
    """A callable accepting the example's first step; returns its posterior."""
    def accept():
        posterior = first_step_posterior(study)
        study.accept("Extra-column volume", posterior)
        return posterior
    return accept


class Navigation:
    """Records `on_navigate(target, context)` calls."""

    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, target, context) -> None:
        self.calls.append((target, dict(context)))


@pytest.fixture
def navigation() -> Navigation:
    return Navigation()
