from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from .simulation import run_process

__all__ = ["SensitivityReport", "perturb_parameters", "response_matrix", "analyze_sensitivity"]


def _get_by_path(obj: Any, path: str) -> float:
    for attr in path.split("."):
        obj = getattr(obj, attr)
    # CADET-Process stores some scalar (non-multiplexed-per-component)
    # parameters list-wrapped regardless of component count (e.g. a column's
    # `axial_dispersion`) -- same convention `InstrumentWidget.
    # _make_on_unit_built` already collapses. A genuinely multi-component
    # list (len > 1) isn't a single scalar to perturb and is out of scope
    # here -- only single-value paths are supported.
    if isinstance(obj, (list, tuple)):
        if len(obj) != 1:
            raise ValueError(f"{path!r} is not a single scalar value: {obj!r}")
        obj = obj[0]
    return float(obj)


def _set_by_path(obj: Any, path: str, value: float) -> None:
    *parents, leaf = path.split(".")
    target = obj
    for attr in parents:
        target = getattr(target, attr)
    current = getattr(target, leaf)
    setattr(target, leaf, type(current)([value]) if isinstance(current, (list, tuple)) else value)


def perturb_parameters(
    process: Any,
    parameter_paths: Sequence[str],
    *,
    relative_step: float = 1e-3,
) -> dict[str, tuple[Any, Any, float, float]]:
    """Central finite-difference perturbation of `process` around each parameter path.

    Never touches `process` -- for each path, builds two deep copies with
    that one parameter nudged by `+/- relative_step` of its current value
    (or by the raw `relative_step` as an absolute step when the current value
    is zero, since a relative step around zero is degenerate), then simulates
    both.

    Returns `{path: (result_minus, result_plus, value_minus, value_plus)}`,
    consumed by `response_matrix`.
    """
    results: dict[str, tuple[Any, Any, float, float]] = {}
    for path in parameter_paths:
        base_value = _get_by_path(process, path)
        step = relative_step * base_value if base_value != 0 else relative_step
        value_minus, value_plus = base_value - step, base_value + step

        process_minus = copy.deepcopy(process)
        _set_by_path(process_minus, path, value_minus)
        process_plus = copy.deepcopy(process)
        _set_by_path(process_plus, path, value_plus)

        results[path] = (
            run_process(process_minus), run_process(process_plus), value_minus, value_plus
        )
    return results


def response_matrix(
    perturbed: Mapping[str, tuple[Any, Any, float, float]],
    signal_path: tuple[str, str],
) -> np.ndarray:
    """Stack each parameter's central-difference response into one `n_params x n_timepoints` matrix.

    Each row is `(solution_plus - solution_minus) / (value_plus - value_minus)`
    at `signal_path` (a `(unit_name, port)` pair, the same convention
    `cadetprocessadapter.classify_signal_ports` uses) -- the local sensitivity
    of the simulated signal to that one parameter, in row order matching
    `perturbed`'s iteration order. Every perturbed run is assumed to share the
    same time grid (same process structure, only one parameter changed
    between the minus/plus copies) -- not re-validated here.
    """
    unit, port = signal_path
    rows = []
    for result_minus, result_plus, value_minus, value_plus in perturbed.values():
        solution_minus = result_minus.solution[unit][port].solution
        solution_plus = result_plus.solution[unit][port].solution
        row = (np.asarray(solution_plus) - np.asarray(solution_minus)) / (value_plus - value_minus)
        rows.append(row.ravel())
    return np.stack(rows)


@dataclass(frozen=True)
class SensitivityReport:
    """Local identifiability diagnostic over a selected parameter subset.

    `cosine_similarity[i, j]` is the cosine similarity between parameter i's
    and parameter j's response vectors -- close to 1.0 means an optimizer
    cannot tell the two apart from this signal alone, the classic
    near-degenerate-parameter-pair symptom (close trace agreement can
    coexist with substantially wrong recovered values for such a pair).
    `condition_number` is the response matrix's condition number: large means
    the joint parameter set is poorly constrained overall, even without any
    single pair looking degenerate. `flagged_pairs` lists every pair whose
    similarity meets `analyze_sensitivity`'s `similarity_threshold`, most
    severe first.
    """

    parameter_names: list[str]
    cosine_similarity: np.ndarray
    condition_number: float
    flagged_pairs: list[tuple[str, str, float]]


def _report_from_matrix(
    parameter_names: Sequence[str], matrix: np.ndarray, *, similarity_threshold: float
) -> SensitivityReport:
    """Build a `SensitivityReport` from an already-computed response matrix.

    Split out from `analyze_sensitivity` so the similarity/condition-number/
    flagging arithmetic is testable against a hand-built matrix, without
    running a real CADET-Process simulation.
    """
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    normalized = matrix / norms
    similarity = normalized @ normalized.T
    condition_number = float(np.linalg.cond(matrix))

    flagged: list[tuple[str, str, float]] = []
    for i in range(len(parameter_names)):
        for j in range(i + 1, len(parameter_names)):
            score = float(similarity[i, j])
            if score >= similarity_threshold:
                flagged.append((parameter_names[i], parameter_names[j], score))
    flagged.sort(key=lambda item: item[2], reverse=True)

    return SensitivityReport(
        parameter_names=list(parameter_names),
        cosine_similarity=similarity,
        condition_number=condition_number,
        flagged_pairs=flagged,
    )


def analyze_sensitivity(
    process: Any,
    parameter_paths: Sequence[str],
    signal_path: tuple[str, str],
    *,
    relative_step: float = 1e-3,
    similarity_threshold: float = 0.99,
) -> SensitivityReport:
    """Local forward-sensitivity/identifiability pre-check, meant to run before fitting.

    Call this before spending optimizer budget on a joint fit over
    `parameter_paths` against `signal_path` -- it flags parameter pairs whose
    local response, at `process`'s current operating point, is nearly
    indistinguishable given that one signal.
    """
    perturbed = perturb_parameters(process, parameter_paths, relative_step=relative_step)
    matrix = response_matrix(perturbed, signal_path)
    return _report_from_matrix(parameter_paths, matrix, similarity_threshold=similarity_threshold)
