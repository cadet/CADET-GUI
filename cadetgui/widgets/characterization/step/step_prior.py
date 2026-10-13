"""The parameter store a characterization step starts from, and the fixes written into it."""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from ....characterization import runner
from ....characterization.parameter_store import ParameterStore, transfer_species
from ....characterization.runner import StepSetup
from ....characterization.step_checks import record_assumptions
from ....characterization.study import Study


class StepPrior:
    """The store a step starts from: the last accepted posterior before it, or the initial one."""

    def __init__(self, study: Study, step_name: Callable[[], str]) -> None:
        self._study = study
        self._step_name = step_name

    def store(self) -> ParameterStore:
        """Return the store the step starts from."""
        name = self._step_name()
        names = [s.name for s in self._study.steps]
        return self._study.prior_for(name) if name in names else self._study.current_store

    def source_step(self) -> Optional[str]:
        """Return the accepted step whose posterior `store()` is, or None (initial store)."""
        name = self._step_name()
        names = [s.name for s in self._study.steps]
        before = names[: names.index(name)] if name in names else names
        accepted = [n for n in before if n in self._study.posteriors]
        return accepted[-1] if accepted else None

    def replace(self, store: ParameterStore) -> str:
        """Make `store` the store this step starts from; return where it was written."""
        source = self.source_step()
        if source is None:
            self._study.initial_store = store
            self._study.notify()
        else:
            self._study.accept(source, store)
        return "initial store" if source is None else source

    def species_gaps(self, setup: StepSetup) -> Dict[str, List[str]]:
        """Return the gaps left once the experiment types' assumed values are recorded."""
        prior = self.store()
        try:
            gaps = runner.species_gaps(setup, record_assumptions(setup, prior))
        except Exception:  # noqa: BLE001 -- an unbuildable recipe is reported by problems()
            return {}
        return {path: names for path, names in gaps.items() if path in prior}

    def transfer_species(
        self, setup: StepSetup, note: Optional[str] = None
    ) -> tuple[ParameterStore, str]:
        """Copy single-probe species values onto the missing species; return store and message."""
        prior = self.store()
        gaps = self.species_gaps(setup)
        species = list(dict.fromkeys(name for names in gaps.values() for name in names))
        transferred = transfer_species(prior, list(gaps), species, note=note)
        where = self.replace(transferred)
        return transferred, f"Transferred {', '.join(gaps)} to {', '.join(species)} ({where})."

    def record_assumptions(self, setup: StepSetup) -> tuple[ParameterStore, str]:
        """Write the values `setup`'s experiment types assume; return store and message."""
        store = record_assumptions(setup, self.store())
        where = self.replace(store)
        return store, f"Recorded the assumed values ({where})."
