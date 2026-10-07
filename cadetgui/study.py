"""A characterization study: initial parameter store, comparisons, chain steps and posteriors.

The JSON form is the manifest written by `examples/generate_characterization_chain_data.py`,
plus an optional `posteriors` mapping of step name to the store that step produced and an
optional `components` list (name and role); without it the components are derived from
the measurements.
Data files are referenced relative to the study file; `Study.save` writes or copies every
comparison's data next to the study so the folder is self-contained.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .characterization_guide import (
    COMPONENT_ROLES,
    EXPERIMENT_TYPES,
    PROTEIN,
    SALT,
    SALT_ROLE,
    parameter_label,
)
from .characterization_runner import StepSetup
from .comparison import Comparison
from .experimental_data import write_experimental_csv
from .parameter_store import ParameterStore

__all__ = ["Study", "StudyComponent", "derive_components"]


@dataclass(frozen=True)
class StudyComponent:
    """A molecule the study's measurements inject or elute with, and its role."""

    name: str
    role: str


def _article(role: str) -> str:
    return f"{'an' if role[:1] in 'aeiou' else 'a'} {role}"


def _roles_text(roles: Iterable[str]) -> str:
    return " or ".join(_article(r) for r in roles)


def derive_components(comparisons: Iterable[Comparison]) -> List[StudyComponent]:
    """Return the components `comparisons` use, with roles from their experiment types.

    A probe used by several types gets the first role all of them allow; an untyped
    measurement's probe is a protein. `SALT` is declared first when a recipe carries it.
    """
    allowed: Dict[str, List[Tuple[str, ...]]] = {}
    salt = False
    for comparison in comparisons:
        salt = salt or SALT in comparison.recipe.components
        if not comparison.probe or comparison.probe == SALT:
            continue
        experiment = EXPERIMENT_TYPES.get(comparison.experiment_type or "")
        options = allowed.setdefault(comparison.probe, [])
        if experiment is not None and experiment.probe_roles:
            options.append(experiment.probe_roles)
    derived = [StudyComponent(SALT, SALT_ROLE)] if salt else []
    for name, options in allowed.items():
        common = [r for r in options[0] if all(r in o for o in options)] if options else []
        role = (common or (options[0] if options else (PROTEIN,)))[0]
        derived.append(StudyComponent(name, role))
    return derived


@dataclass
class Study:
    """Mutable container the characterization widgets share.

    `posteriors` holds, per step name, the store accepted for that step. `current_store`
    is the posterior of the last step (in `steps` order) that has one, else
    `initial_store`, which is what the next step starts from.

    `components` are the declared molecules with their `COMPONENT_ROLES` role. Stored
    values are keyed by component name, so the name is what links values across steps.
    Adding or replacing a measurement declares its probe (and `SALT`) if missing.
    """

    initial_store: ParameterStore = field(default_factory=ParameterStore)
    comparisons: List[Comparison] = field(default_factory=list)
    steps: List[StepSetup] = field(default_factory=list)
    posteriors: Dict[str, ParameterStore] = field(default_factory=dict)
    description: str = ""
    base_dir: Optional[Path] = None
    components: List[StudyComponent] = field(default_factory=list)
    _listeners: List[Callable[[], None]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        """Derive `components` from the measurements when none are given."""
        if not self.components:
            self.components = derive_components(self.comparisons)

    def add_listener(self, fn: Callable[[], None]) -> None:
        """Call `fn()` after every change made through this object's methods."""
        self._listeners.append(fn)

    def remove_listener(self, fn: Callable[[], None]) -> None:
        """Stop calling `fn`; unknown listeners are ignored."""
        if fn in self._listeners:
            self._listeners.remove(fn)

    def notify(self) -> None:
        """Tell listeners the study changed; call after editing attributes directly."""
        for fn in list(self._listeners):
            fn()

    def comparison(self, name: str) -> Comparison:
        """Return the comparison called `name`."""
        for comparison in self.comparisons:
            if comparison.name == name:
                return comparison
        raise KeyError(f"No comparison named {name!r}.")

    def upsert_comparison(self, comparison: Comparison) -> None:
        """Add `comparison`, replacing one with the same name."""
        self.comparisons = [c for c in self.comparisons if c.name != comparison.name]
        self.comparisons.append(comparison)
        self._declare(comparison)
        self.notify()

    def replace_comparison(self, name: str, comparison: Comparison) -> None:
        """Put `comparison` in place of the one called `name`, in the list and in every step."""
        if comparison.name != name and any(c.name == comparison.name for c in self.comparisons):
            raise ValueError(f"A comparison named {comparison.name!r} already exists.")
        self.comparison(name)
        self.comparisons = [comparison if c.name == name else c for c in self.comparisons]
        for step in self.steps:
            step.comparisons = [comparison if c.name == name else c for c in step.comparisons]
            if step.excluded is not None:
                step.excluded = tuple(comparison.name if n == name else n for n in step.excluded)
        self._declare(comparison)
        self.notify()

    def steps_using(self, name: str) -> List[str]:
        """Return the names of the steps that fit the comparison called `name`."""
        return [s.name for s in self.steps if any(c.name == name for c in s.comparisons)]

    def remove_comparison(self, name: str, *, from_steps: bool = False) -> None:
        """Remove the comparison called `name`.

        Raises while a step still fits it, unless `from_steps` takes it out of those steps
        too (accepted posteriors are kept). Steps that leave it out forget it.
        """
        users = self.steps_using(name)
        if users and not from_steps:
            raise ValueError(f"Comparison {name!r} is used by step(s) {', '.join(users)}.")
        self.steps = [
            replace(
                step,
                comparisons=[c for c in step.comparisons if c.name != name],
                excluded=step.excluded and tuple(n for n in step.excluded if n != name),
            ) if step.name in users or name in (step.excluded or ()) else step
            for step in self.steps
        ]
        self.comparisons = [c for c in self.comparisons if c.name != name]
        self.notify()

    def component(self, name: str) -> Optional[StudyComponent]:
        """Return the declared component called `name`, or None."""
        return next((c for c in self.components if c.name == name), None)

    def measurements_using(self, name: str) -> List[str]:
        """Return the names of the measurements whose probe or recipe uses component `name`."""
        return [
            c.name for c in self.comparisons
            if c.probe == name or name in c.recipe.components
        ]

    def _declare(self, comparison: Comparison) -> None:
        for derived in derive_components([comparison]):
            if self.component(derived.name) is None:
                if derived.role == SALT_ROLE:
                    self.components.insert(0, derived)
                else:
                    self.components.append(derived)

    def _check_component(self, name: str, role: str) -> None:
        if role not in COMPONENT_ROLES:
            raise ValueError(f"Unknown role {role!r}; pick one of {', '.join(COMPONENT_ROLES)}.")
        if not name:
            raise ValueError("A component needs a name.")
        if name == SALT and role != SALT_ROLE:
            raise ValueError(
                f"{SALT!r} is reserved for the salt of gradient and breakthrough runs."
            )
        if role == SALT_ROLE and name != SALT:
            raise ValueError(
                f"The salt component is called {SALT!r}; gradient and breakthrough recipes "
                "use that name."
            )

    def add_component(self, name: str, role: str) -> StudyComponent:
        """Declare component `name` with `role`; raises if the name is taken."""
        name = name.strip()
        self._check_component(name, role)
        if self.component(name) is not None:
            raise ValueError(f"A component called {name!r} is already declared.")
        component = StudyComponent(name, role)
        if role == SALT_ROLE:
            self.components.insert(0, component)
        else:
            self.components.append(component)
        self.notify()
        return component

    def set_component_role(self, name: str, role: str) -> None:
        """Give the declared component `name` another role."""
        self._check_component(name, role)
        if self.component(name) is None:
            raise KeyError(f"No component named {name!r}.")
        self.components = [
            StudyComponent(name, role) if c.name == name else c for c in self.components
        ]
        self.notify()

    def stored_values_for(self, name: str) -> Dict[str, List[str]]:
        """Return `{where: [parameter labels]}` for the stores holding values keyed by `name`."""
        stores = [("the starting values", self.initial_store)]
        stores += [(f"accepted step {step}", store) for step, store in self.posteriors.items()]
        found: Dict[str, List[str]] = {}
        for where, store in stores:
            labels = [
                parameter_label(path) for path, entry in store.entries.items()
                if path in store.specs and store.specs[path].species_indexed
                and name in entry.value
            ]
            if labels:
                found[where] = labels
        return found

    def rename_component(self, old: str, new: str) -> None:
        """Rename component `old` in the declaration and in every measurement using it.

        Refused while any store holds values keyed by `old`: accepted results and their
        provenance name the component, and re-keying them would silently change which
        values a later step applies.
        """
        new = new.strip()
        current = self.component(old)
        if current is None:
            raise KeyError(f"No component named {old!r}.")
        if new == old:
            return
        if current.role == SALT_ROLE:
            raise ValueError(f"The salt component's name {SALT!r} is fixed.")
        self._check_component(new, current.role)
        if self.component(new) is not None:
            raise ValueError(f"A component called {new!r} is already declared.")
        held = self.stored_values_for(old)
        if held:
            where = "; ".join(f"{w}: {', '.join(labels)}" for w, labels in held.items())
            raise ValueError(
                f"{old} cannot be renamed: values are stored under its name ({where}). "
                "Renaming would detach them. Declare a new component instead."
            )
        for comparison in self.comparisons:
            if comparison.probe == old:
                comparison.probe = new
            if comparison.components:
                comparison.components = [new if n == old else n for n in comparison.components]
            if old in comparison.recipe.components:
                comparison.recipe = replace(
                    comparison.recipe,
                    components=[new if n == old else n for n in comparison.recipe.components],
                )
        self.components = [
            StudyComponent(new, c.role) if c.name == old else c for c in self.components
        ]
        self.notify()

    def remove_component(self, name: str) -> None:
        """Remove component `name`; raises while a measurement uses it."""
        if self.component(name) is None:
            raise KeyError(f"No component named {name!r}.")
        users = self.measurements_using(name)
        if users:
            raise ValueError(f"{name} is used by measurement(s) {', '.join(users)}.")
        self.components = [c for c in self.components if c.name != name]
        self.notify()

    def component_problems(self, comparison: Comparison) -> List[str]:
        """Return problems with `comparison`'s probe: undeclared, or a role its type forbids."""
        experiment = EXPERIMENT_TYPES.get(comparison.experiment_type or "")
        roles = experiment.probe_roles if experiment is not None else ()
        probe = comparison.probe
        if not probe:
            return [f"No component picked; {experiment.label} needs {_roles_text(roles)}."] if (
                roles
            ) else []
        component = self.component(probe)
        if component is None:
            return [f"{probe!r} is not a declared component."]
        if roles and component.role not in roles:
            return [
                f"{experiment.label} uses {probe!r} as {_roles_text(roles)}, but {probe} is "
                f"declared as {_article(component.role)}."
            ]
        return []

    def measurement_problems(self, comparison: Comparison) -> List[str]:
        """Return `comparison.problems()` plus its component problems."""
        return comparison.problems() + self.component_problems(comparison)

    def upsert_step(self, step: StepSetup) -> None:
        """Add `step` at the end of the chain, or replace the step with the same name in place."""
        names = [s.name for s in self.steps]
        if step.name in names:
            self.steps[names.index(step.name)] = step
        else:
            self.steps.append(step)
        self.notify()

    def prior_for(self, step_name: str) -> ParameterStore:
        """Return the store `step_name` starts from: the latest accepted posterior before it."""
        store = self.initial_store
        for step in self.steps:
            if step.name == step_name:
                return store
            store = self.posteriors.get(step.name, store)
        raise KeyError(f"No step named {step_name!r}.")

    @property
    def current_store(self) -> ParameterStore:
        """The store after the last accepted step."""
        store = self.initial_store
        for step in self.steps:
            store = self.posteriors.get(step.name, store)
        return store

    def accept(self, step_name: str, posterior: ParameterStore) -> None:
        """Record `posterior` as the accepted result of `step_name`."""
        self.posteriors[step_name] = posterior
        self.notify()

    def to_dict(self) -> Dict[str, Any]:
        """Return the JSON form."""
        return {
            "description": self.description,
            "initial_store": self.initial_store.to_dict(),
            "steps": [step.to_dict() for step in self.steps],
            "comparisons": [comparison.to_dict() for comparison in self.comparisons],
            "components": [{"name": c.name, "role": c.role} for c in self.components],
            "posteriors": {name: store.to_dict() for name, store in self.posteriors.items()},
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any], base_dir: "Path | str | None" = None) -> "Study":
        """Rebuild from `to_dict`'s form; with `base_dir`, comparisons load their data files."""
        comparisons = [Comparison.from_dict(c, base_dir=base_dir) for c in raw["comparisons"]]
        by_name = {c.name: c for c in comparisons}
        return cls(
            initial_store=ParameterStore.from_dict(raw["initial_store"]),
            comparisons=comparisons,
            steps=[StepSetup.from_dict(s, by_name) for s in raw.get("steps", [])],
            posteriors={
                name: ParameterStore.from_dict(store)
                for name, store in (raw.get("posteriors") or {}).items()
            },
            description=raw.get("description", ""),
            base_dir=Path(base_dir) if base_dir is not None else None,
            components=[StudyComponent(c["name"], c["role"]) for c in raw.get("components", [])],
        )

    @classmethod
    def load(cls, path: "Path | str") -> "Study":
        """Read a study file; data files resolve relative to it."""
        path = Path(path)
        return cls.from_dict(json.loads(path.read_text()), base_dir=path.parent)

    def save(self, path: "Path | str") -> Path:
        """Write the study to `path` as JSON, with every comparison's data next to it.

        See `place_data_files`; afterwards `base_dir` is `path`'s folder.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        changed = self.place_data_files(path.parent)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")
        moved = self.base_dir is None or Path(self.base_dir).resolve() != path.parent.resolve()
        self.base_dir = path.parent
        if changed or moved:
            self.notify()
        return path

    def place_data_files(self, folder: "Path | str") -> List[str]:
        """Make every comparison's `data_file` resolve inside `folder`.

        A file found under `base_dir` is copied; a comparison with only a loaded `run`
        gets that run written with `write_experimental_csv`. An existing different file
        in `folder` is never overwritten: the data goes to a fresh name instead and
        `data_file` is rewritten. Comparisons sharing a source share the placed file.
        Returns the names of comparisons whose `data_file` changed.
        """
        folder = Path(folder)
        placed: Dict[Any, str] = {}
        changed: List[str] = []
        for comparison in self.comparisons:
            source = self._source_file(comparison)
            if source is not None:
                key: Any = ("file", source.resolve())
            elif comparison.run is not None:
                key = ("run", id(comparison.run))
            else:
                continue
            if key not in placed:
                content = (
                    source.read_bytes() if source is not None
                    else write_experimental_csv(comparison.run)
                )
                placed[key] = _place(folder, comparison.data_file or comparison.name, content)
            if comparison.data_file != placed[key]:
                comparison.data_file = placed[key]
                changed.append(comparison.name)
        return changed

    def _source_file(self, comparison: Comparison) -> Optional[Path]:
        if self.base_dir is None or not comparison.data_file:
            return None
        source = Path(self.base_dir) / comparison.data_file
        return source if source.is_file() else None


def _place(folder: Path, name: str, content: bytes) -> str:
    """Write `content` under `folder` as `name` (or a free variant); return the relative name."""
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.name:
        relative = Path(relative.name or "data")
    stem = re.sub(r"[^\w.-]+", "_", relative.stem).strip("_") or "data"
    parent = relative.parent
    candidate = parent / f"{stem}.csv" if relative.suffix.lower() != ".csv" else relative
    i = 2
    while True:
        target = folder / candidate
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            return candidate.as_posix()
        if target.is_file() and target.read_bytes() == content:
            return candidate.as_posix()
        candidate = parent / f"{stem}_{i}.csv"
        i += 1
