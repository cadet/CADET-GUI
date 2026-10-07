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
    # CADET-Process may list-wrap a scalar (e.g. a column's `axial_dispersion`).
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
    """Simulate two deep copies of `process` per path, nudged by `+/- relative_step`.

    The step is relative to the current value, or absolute when that is zero.
    Returns `{path: (result_minus, result_plus, value_minus, value_plus)}`; `process`
    itself is never modified.
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
    """Stack each parameter's central-difference response into an `n_params x n_timepoints` matrix.

    Each row is `(solution_plus - solution_minus) / (value_plus - value_minus)` at
    `signal_path` (a `(unit_name, port)` pair); all runs must share one time grid.
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
    """Local identifiability diagnostic over a parameter subset.

    `cosine_similarity[i, j]` near 1.0 means parameters i and j cannot be told apart
    from this signal. A large `condition_number` means the set is poorly constrained
    overall. `flagged_pairs` lists pairs at or above `similarity_threshold`, most
    similar first.
    """

    parameter_names: list[str]
    cosine_similarity: np.ndarray
    condition_number: float
    flagged_pairs: list[tuple[str, str, float]]


def _report_from_matrix(
    parameter_names: Sequence[str], matrix: np.ndarray, *, similarity_threshold: float
) -> SensitivityReport:
    """Build a `SensitivityReport` from a response matrix (testable without simulating)."""
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
    """Flag parameter pairs whose local response at `process` is nearly indistinguishable.

    Meant to run before a joint fit over `parameter_paths` against `signal_path`.
    """
    perturbed = perturb_parameters(process, parameter_paths, relative_step=relative_step)
    matrix = response_matrix(perturbed, signal_path)
    return _report_from_matrix(parameter_paths, matrix, similarity_threshold=similarity_threshold)
