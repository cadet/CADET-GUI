"""Species-aware parameter store for chained characterization steps.

A characterization run maps a prior parameter set and measured data to a
posterior parameter set; the posterior is written once and never edited, so
the store is a value passed along a chain rather than a file steps mutate.
Two rules follow from that: whether a parameter is species-indexed is
declared (via `ParameterSpec`), never inferred from a value's shape, and
species are addressed by name in storage, translated to CADET's positional
indices only when a value is applied to or read from a process.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from CADETProcess.dataStructure import Sized
from CADETProcess.processModel import ComponentSystem

__all__ = [
    "ParameterSpec",
    "Provenance",
    "Entry",
    "ParameterStore",
    "species_index",
    "spec_for",
    "apply_store",
    "has_parameter",
    "read_process",
    "Step",
    "ChainError",
    "check_chain",
    "missing_requirements",
    "transfer_species",
]


def species_index(name: str, component_system: ComponentSystem) -> int:
    """Return the position of species `name` in CADET parameter arrays.

    CADET indexes parameter arrays by species, not by component; resolving
    against component names instead only works while every component carries
    exactly one species.

    Raises
    ------
    KeyError
        If `name` is not part of `component_system`.
    """
    indices = component_system.species_indices
    if name not in indices:
        raise KeyError(f"Species '{name}' is not in the component system {list(indices)}.")
    return indices[name]


@dataclass(frozen=True)
class ParameterSpec:
    """Declaration of how one model parameter is stored.

    `path` is a CADET-Process parameter path (e.g.
    `"flow_sheet.column.bed_porosity"`), the same string
    `OptimizationProblem.add_variable` takes. `species_indexed` says whether
    CADET stores one value per species for this parameter.
    """

    path: str
    species_indexed: bool = False


@dataclass(frozen=True)
class Provenance:
    """Record of how a stored value came to be.

    `probe` names the species used to probe the parameter (relevant when a
    parameter is apparent and probe-dependent), `source` identifies the
    measured data a fit used, `model` a model variant, `metric` the achieved
    objective values, and `note` is free text for assumed (not fitted)
    values.
    """

    step: str
    probe: Optional[str] = None
    source: Optional[str] = None
    model: Optional[str] = None
    metric: Optional[dict] = None
    note: Optional[str] = None


@dataclass(frozen=True)
class Entry:
    """A stored value together with its provenance.

    `value` is a scalar, or one value per species keyed by species name;
    which applies is fixed by the parameter's `ParameterSpec`, not inferred
    from this field.
    """

    value: Any
    provenance: Provenance


@dataclass(frozen=True)
class ParameterStore:
    """Immutable snapshot of model parameters at one point in a chain.

    `updated` returns a new store rather than modifying this one, so a
    step's input stays readable after it has run.
    """

    entries: Mapping[str, Entry] = field(default_factory=dict)
    specs: Mapping[str, ParameterSpec] = field(default_factory=dict)
    step: Optional[str] = None
    prior: Optional[str] = None

    def spec(self, path: str) -> ParameterSpec:
        """Return the declaration for `path`, raising if it was never declared."""
        if path not in self.specs:
            raise KeyError(
                f"Parameter '{path}' is not declared. Add a ParameterSpec instead of "
                "relying on the value's shape."
            )
        return self.specs[path]

    def __contains__(self, path: str) -> bool:
        """Return whether a value is stored for `path`."""
        return path in self.entries

    def value(self, path: str, species: Optional[str] = None) -> Any:
        """Return the stored value for `path`; `species` is required iff species-indexed."""
        spec = self.spec(path)
        entry = self.entries[path]

        if not spec.species_indexed:
            if species is not None:
                raise ValueError(f"'{path}' is not species-indexed.")
            return entry.value

        if species is None:
            return dict(entry.value)
        return entry.value[species]

    def to_cadet(self, path: str, component_system: ComponentSystem) -> Any:
        """Return the value for `path` in the layout CADET expects.

        Species-indexed parameters become a list ordered by species index;
        scalars are returned unchanged. A species of `component_system`
        without a stored value is an error rather than something to pad with
        a default.
        """
        spec = self.spec(path)
        entry = self.entries[path]

        if not spec.species_indexed:
            return entry.value

        missing = [s for s in component_system.species if s not in entry.value]
        if missing:
            raise KeyError(f"'{path}' has no value for species {missing}.")
        return [
            entry.value[name]
            for name in sorted(
                component_system.species,
                key=lambda n: species_index(n, component_system),
            )
        ]

    def from_cadet(self, path: str, value: Any, component_system: ComponentSystem) -> Any:
        """Return `value`, as read off a CADET object at `path`, in the store's own layout.

        Inverse of `to_cadet`: turns a species-index-ordered list back into a
        dict keyed by species name. Scalars pass through unchanged.
        """
        spec = self.spec(path)
        if not spec.species_indexed:
            return value
        return {
            name: value[species_index(name, component_system)]
            for name in component_system.species
        }

    def updated(
        self,
        values: Mapping[str, Any],
        provenance: Provenance,
        specs: Optional[Mapping[str, ParameterSpec]] = None,
    ) -> "ParameterStore":
        """Return a new store with `values` written on top of this one.

        Species-indexed parameters take a dict keyed by species name, merged
        into any existing entry so that a step fitting one species leaves
        the others intact. `specs` declares `ParameterSpec`s for paths this
        store has not seen before, so a caller can add paths lazily instead
        of pre-declaring every path upfront.
        """
        all_specs = dict(self.specs)
        if specs:
            all_specs.update(specs)

        entries = dict(self.entries)
        for path, value in values.items():
            if path not in all_specs:
                raise KeyError(
                    f"Parameter '{path}' is not declared. Pass its ParameterSpec via `specs`."
                )
            spec = all_specs[path]
            if spec.species_indexed:
                if not isinstance(value, Mapping):
                    raise TypeError(
                        f"'{path}' is species-indexed and needs a mapping keyed by "
                        f"species name, got {type(value).__name__}."
                    )
                merged = dict(entries[path].value) if path in entries else {}
                merged.update(value)
                value = merged
            elif isinstance(value, Mapping):
                raise TypeError(
                    f"'{path}' is not species-indexed but was given a mapping. Probe "
                    "dependence is recorded in provenance, not in the value."
                )
            entries[path] = Entry(value=value, provenance=provenance)

        return replace(
            self, entries=entries, specs=all_specs, step=provenance.step, prior=self.step
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation of this store."""
        return {
            "step": self.step,
            "prior": self.prior,
            "specs": {
                path: {"species_indexed": spec.species_indexed}
                for path, spec in sorted(self.specs.items())
            },
            "entries": {
                path: {
                    "value": entry.value,
                    "provenance": {
                        k: v for k, v in asdict(entry.provenance).items() if v is not None
                    },
                }
                for path, entry in sorted(self.entries.items())
            },
        }

    @classmethod
    def from_dict(
        cls, raw: Mapping[str, Any], specs: Optional[Mapping[str, ParameterSpec]] = None
    ) -> "ParameterStore":
        """Rebuild a store from `to_dict`'s output.

        Without `specs`, the declarations saved in `raw` are used. With `specs`, a
        saved declaration that disagrees with the given one raises, so reading an old
        snapshot against today's declarations surfaces a parameter whose meaning
        changed.
        """
        saved = {
            path: ParameterSpec(path, bool(item.get("species_indexed", False)))
            for path, item in (raw.get("specs") or {}).items()
        }
        if specs is None:
            specs = saved
        else:
            changed = [p for p, s in saved.items() if p in specs and specs[p] != s]
            if changed:
                raise ValueError(f"Saved declarations disagree with the given specs: {changed}.")
            specs = {**saved, **specs}
        entries = {
            key: Entry(value=item["value"], provenance=Provenance(**item["provenance"]))
            for key, item in raw["entries"].items()
        }
        return cls(entries=entries, specs=specs, step=raw.get("step"), prior=raw.get("prior"))

    def save(self, path: "Path | str") -> Path:
        """Write this store to `path` as JSON and return the path."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as handle:
            json.dump(self.to_dict(), handle, indent=4)
            handle.write("\n")
        return path

    @classmethod
    def load(
        cls, path: "Path | str", specs: Optional[Mapping[str, ParameterSpec]] = None
    ) -> "ParameterStore":
        """Read a store written by `save`."""
        with open(path) as handle:
            raw = json.load(handle)
        return cls.from_dict(raw, specs)


def has_parameter(process: Any, path: str) -> bool:
    """Return whether `process` carries the parameter at `path` (bypassed units don't)."""
    target, _, attribute = path.rpartition(".")
    obj = _resolve(process, target)
    return obj is not None and hasattr(obj, attribute)


def _resolve(root: Any, path: str) -> Any:
    """Walk a dotted path from `root`; return `None` if any step is absent."""
    obj = root
    for part in path.split("."):
        if not part:
            continue
        try:
            obj = obj[part] if _is_indexable(obj, part) else getattr(obj, part)
        except (AttributeError, KeyError):
            return None
    return obj


def _is_indexable(obj: Any, key: str) -> bool:
    """Return whether `key` should be looked up by item rather than by attribute."""
    return hasattr(obj, "__getitem__") and not hasattr(obj, key)


def _descriptor(cls: type, name: str) -> Any | None:
    """Return the CADET-Process parameter descriptor backing `name` on `cls`, or `None`.

    Some parameters are properties over a differently named private
    descriptor (e.g. binding-model `q`, `cp`); fall back to `_name`.
    """
    desc = getattr(cls, name, None)
    if isinstance(desc, property):
        desc = getattr(cls, f"_{name}", None)
    return desc if hasattr(desc, "default") else None


def spec_for(process: Any, path: str) -> ParameterSpec:
    """Infer a `ParameterSpec` for `path` from the CADET-Process descriptor it targets.

    `species_indexed` is read off the descriptor's declared size (a `Sized`
    descriptor with `size == ("n_comp",)`), never off a runtime value.

    Raises
    ------
    KeyError
        If `path` does not resolve to a described parameter on `process`.
    """
    target, _, attribute = path.rpartition(".")
    obj = _resolve(process, target)
    if obj is None or not hasattr(obj, attribute):
        raise KeyError(f"'{path}' is not a parameter on {process!r}.")

    descriptor = _descriptor(type(obj), attribute)
    if descriptor is None:
        raise KeyError(f"'{path}' has no CADET-Process descriptor to read.")

    species_indexed = isinstance(descriptor, Sized) and descriptor.size == ("n_comp",)
    return ParameterSpec(path=path, species_indexed=species_indexed)


def apply_store(process: Any, store: ParameterStore) -> list[str]:
    """Set every parameter of `store` that `process` actually has; return the applied paths.

    A path the process doesn't carry is skipped rather than raising: a
    characterization run bypasses parts of the system, so a store holding
    the whole model is routinely applied to a process that only contains
    part of it.
    """
    component_system = process.component_system
    applied = []

    for path in store.entries:
        target, _, attribute = path.rpartition(".")
        obj = _resolve(process, target)
        if obj is None or not hasattr(obj, attribute):
            continue
        setattr(obj, attribute, store.to_cadet(path, component_system))
        applied.append(path)

    return applied


def read_process(process: Any, paths: Iterable[str], store: ParameterStore) -> dict[str, Any]:
    """Read `paths` off `process`, translated back into the store's own layout.

    Raises
    ------
    KeyError
        If `process` does not carry one of `paths`.
    """
    component_system = process.component_system
    values = {}
    for path in paths:
        target, _, attribute = path.rpartition(".")
        obj = _resolve(process, target)
        if obj is None or not hasattr(obj, attribute):
            raise KeyError(f"'{path}' is not a parameter on {process!r}.")
        values[path] = store.from_cadet(path, getattr(obj, attribute), component_system)
    return values


class ChainError(Exception):
    """Raised when a chain of steps is inconsistent, before anything runs."""


@dataclass(frozen=True)
class Step:
    """One characterization step: what it needs already fixed, what it determines."""

    name: str
    requires: Sequence[str] = ()
    provides: Sequence[str] = ()


def check_chain(steps: Sequence[Step], initial: ParameterStore) -> None:
    """Validate that every step's `requires` are met by the time it runs.

    Raises
    ------
    ChainError
        If a step requires a parameter that neither `initial` nor an earlier
        step provides, if a path is undeclared in `initial`, or if two steps
        share a name.
    """
    seen = set(initial.entries)
    names: set[str] = set()

    for position, step in enumerate(steps, start=1):
        if step.name in names:
            raise ChainError(f"Duplicate step name '{step.name}'.")
        names.add(step.name)

        for path in (*step.requires, *step.provides):
            try:
                initial.spec(path)
            except KeyError as error:
                raise ChainError(f"Step {position} ('{step.name}'): {error}") from error

        missing = [path for path in step.requires if path not in seen]
        if missing:
            raise ChainError(
                f"Step {position} ('{step.name}') requires {missing}, which no earlier "
                "step provides."
            )
        seen.update(step.provides)


def missing_requirements(step: Step, store: ParameterStore) -> list[str]:
    """Return `step.requires` entries absent from `store`, without raising."""
    return [path for path in step.requires if path not in store]


def transfer_species(
    store: ParameterStore, paths: Iterable[str], species: Sequence[str], note: Optional[str] = None
) -> ParameterStore:
    """Copy species-indexed values probed with one species onto `species`.

    A value determined with one probe (a tubing dispersion fitted on one tracer) says
    nothing about another species by itself; carrying it over is a modelling assumption,
    so it is an explicit step that keeps the original provenance and appends a note
    naming the transfer.

    Raises
    ------
    KeyError
        If a path is not stored, not species-indexed, or was probed with more than one
        species, which leaves no single value to transfer.
    """
    for path in paths:
        if path not in store:
            raise KeyError(f"'{path}' has no stored value to transfer.")
        if not store.spec(path).species_indexed:
            raise KeyError(f"'{path}' is not species-indexed.")
        entry = store.entries[path]
        probed = sorted(entry.value)
        if len(probed) != 1:
            raise KeyError(
                f"'{path}' was probed with {probed}; transferring needs exactly one probe species."
            )
        (probe,) = probed
        targets = [name for name in species if name not in entry.value]
        if not targets:
            continue
        text = f"probed with {probe}, transferred unchanged to {', '.join(targets)}"
        if note:
            text = f"{text}: {note}"
        if entry.provenance.note:
            text = f"{entry.provenance.note}; {text}"
        store = store.updated(
            {path: {name: entry.value[probe] for name in targets}},
            replace(entry.provenance, note=text),
        )
    return store
