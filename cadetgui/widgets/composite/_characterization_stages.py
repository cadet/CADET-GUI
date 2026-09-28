from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, Mapping, Optional

from CADETProcess.characterization import (
    CharacterizeAdsorptionParameters,
    CharacterizeBed,
    CharacterizeCapacity,
    CharacterizeParticles,
    CharacterizePreInjection,
    CharacterizeTubing,
)

from ...cadetprocessadapter import FieldSpec

Stage = Literal["periphery", "pre_injection", "bed", "particles", "adsorption", "capacity"]

_M = r"\mathrm{m}"
_DISPERSION = r"\frac{\mathrm{m}^{2}}{\mathrm{s}}"


@dataclass(frozen=True)
class WriteTarget:
    """Where one fitted variable is written back.

    `field` is the target's real CADET-Process attribute, which can differ from the
    variable name (`mixer_volume` is the mixer's `init_liquid_volume`).
    """

    form: Literal["instrument", "column", "binding"]
    unit: Optional[str]
    field: str

    def resolve(self, process: Any) -> Any:
        """Return the object of `process` this target writes to."""
        flow_sheet = process.flow_sheet
        if self.form == "instrument":
            return flow_sheet[self.unit]
        if self.form == "column":
            return flow_sheet.column
        return flow_sheet.column.binding_model


@dataclass(frozen=True)
class StageSpec:
    """One characterization stage: its solver class, bound-override fields and write-backs."""

    label: str
    characterize_cls: type
    extra_kwargs: Dict[str, Any]
    fields: tuple[FieldSpec, ...]
    write_targets: Dict[str, WriteTarget]

    def apply_values(self, process: Any, values: Mapping[str, float]) -> None:
        """Set `{variable: value}` directly on `process`."""
        for name, value in values.items():
            target = self.write_targets.get(name)
            if target is None:
                continue
            unit = target.resolve(process)
            current = getattr(unit, target.field)
            wrapped = type(current)([value]) if isinstance(current, (list, tuple)) else value
            setattr(unit, target.field, wrapped)

    def read_values(self, process: Any) -> Dict[str, float]:
        """Return `{variable: value}` as currently set on `process`."""
        values: Dict[str, float] = {}
        for name, target in self.write_targets.items():
            current = getattr(target.resolve(process), target.field)
            values[name] = current[0] if isinstance(current, (list, tuple)) else current
        return values

    def group_by_form(
        self, values: Mapping[str, float]
    ) -> Dict[tuple[str, Optional[str]], Dict[str, float]]:
        """Group `{variable: value}` into `{(form, unit): {field: value}}`."""
        groups: Dict[tuple[str, Optional[str]], Dict[str, float]] = {}
        for name, value in values.items():
            target = self.write_targets.get(name)
            if target is not None:
                groups.setdefault((target.form, target.unit), {})[target.field] = value
        return groups


_STATIC_STAGE_SPECS: Dict[str, StageSpec] = {
    "pre_injection": StageSpec(
        label="System periphery (pre-injection tubing + mixer)",
        characterize_cls=CharacterizePreInjection,
        extra_kwargs={},
        fields=(
            FieldSpec(
                "tubing_pre_injection_length", "float", label="Pre-injection tubing length",
                min=1e-3, max=5.0, default=0.1, units=_M,
            ),
            FieldSpec(
                "mixer_volume", "float", label="Mixer volume",
                min=1e-9, max=1e-3, default=1e-6, units=r"\mathrm{m}^{3}",
            ),
        ),
        write_targets={
            "tubing_pre_injection_length": WriteTarget(
                "instrument", "tubing_pre_injection", "length"
            ),
            "mixer_volume": WriteTarget("instrument", "mixer", "init_liquid_volume"),
        },
    ),
    "bed": StageSpec(
        label="Column bed (porosity & axial dispersion)",
        characterize_cls=CharacterizeBed,
        extra_kwargs={},
        fields=(
            FieldSpec("bed_porosity", "float", label="Bed porosity", min=0.2, max=0.8, default=0.4),
            FieldSpec(
                "axial_dispersion", "float", label="Axial dispersion",
                min=1e-12, max=1e-4, default=1e-7, units=_DISPERSION,
            ),
        ),
        write_targets={
            "bed_porosity": WriteTarget("column", None, "bed_porosity"),
            "axial_dispersion": WriteTarget("column", None, "axial_dispersion"),
        },
    ),
    "particles": StageSpec(
        label="Particle transport (film diffusion)",
        characterize_cls=CharacterizeParticles,
        extra_kwargs={"include_film_diffusion": True},
        fields=(
            FieldSpec(
                "film_diffusion", "float", label="Film diffusion",
                min=1e-9, max=1e-3, default=1e-5, units=r"\frac{\mathrm{m}}{\mathrm{s}}",
            ),
        ),
        write_targets={"film_diffusion": WriteTarget("column", None, "film_diffusion")},
    ),
    # Rapid equilibrium only: the kinetic mode's dependent variables aren't supported
    # by `run_optimization`.
    "adsorption": StageSpec(
        label="Binding (rapid equilibrium)",
        characterize_cls=CharacterizeAdsorptionParameters,
        extra_kwargs={"is_kinetic": False},
        fields=(
            FieldSpec(
                "characteristic_charge", "float", label="Characteristic charge",
                min=0.1, max=50.0, default=5.0,
            ),
            FieldSpec(
                "adsorption_rate", "float", label="Equilibrium constant",
                min=1e-3, max=1e6, default=1.0,
            ),
        ),
        write_targets={
            "characteristic_charge": WriteTarget("binding", None, "characteristic_charge"),
            "adsorption_rate": WriteTarget("binding", None, "adsorption_rate"),
        },
    ),
    "capacity": StageSpec(
        label="Binding capacity",
        characterize_cls=CharacterizeCapacity,
        extra_kwargs={},
        fields=(
            FieldSpec(
                "capacity", "float", label="Capacity",
                min=1.0, max=1000.0, default=100.0, units=r"\mathrm{mM}",
            ),
        ),
        write_targets={"capacity": WriteTarget("binding", None, "capacity")},
    ),
}


def _tubing_spec(unit: str) -> StageSpec:
    length, dispersion = f"{unit}_length", f"{unit}_axial_dispersion"
    return StageSpec(
        label=f"System periphery ({unit})",
        characterize_cls=CharacterizeTubing,
        extra_kwargs={"tubing": unit},
        fields=(
            FieldSpec(
                length, "float", label="Length", min=1e-3, max=5.0, default=0.1, units=_M
            ),
            FieldSpec(
                dispersion, "float", label="Axial dispersion",
                min=1e-12, max=1e-4, default=1e-7, units=_DISPERSION,
            ),
        ),
        write_targets={
            length: WriteTarget("instrument", unit, "length"),
            dispersion: WriteTarget("instrument", unit, "axial_dispersion"),
        },
    )


def stage_spec(stage: Stage, tubing_unit: Optional[str] = None) -> StageSpec:
    """Return the spec for `stage`; the "periphery" stage is parametrized by `tubing_unit`."""
    if stage == "periphery":
        if tubing_unit is None:
            raise ValueError('stage="periphery" requires tubing_unit=...')
        return _tubing_spec(tubing_unit)
    if tubing_unit is not None:
        raise ValueError(f"tubing_unit only applies to stage='periphery', got {stage!r}")
    return _STATIC_STAGE_SPECS[stage]
