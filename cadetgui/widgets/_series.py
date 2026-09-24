from __future__ import annotations

from typing import Any, Optional

import numpy as np

__all__ = ["decimate_minmax", "solution_series"]


def decimate_minmax(
    times: np.ndarray, values: np.ndarray, max_points: int = 2000
) -> tuple[list[float], list[float]]:
    """Thin a long trace to about `max_points`, keeping each bucket's min and max so peaks survive."""
    n = len(times)
    if n <= max_points:
        return times.tolist(), values.tolist()
    edges = np.linspace(0, n, max(max_points // 2, 1) + 1, dtype=int)
    keep = {0, n - 1}
    for start, stop in zip(edges[:-1], edges[1:]):
        if stop <= start:
            continue
        segment = values[start:stop]
        keep.add(start + int(np.argmin(segment)))
        keep.add(start + int(np.argmax(segment)))
    idx = np.array(sorted(keep))
    return times[idx].tolist(), values[idx].tolist()


def solution_series(solution: Any, max_points: int = 2000) -> Optional[list[dict[str, Any]]]:
    """One chart series per component (time in minutes), or None if not a time x component trace."""
    values = np.asarray(solution.solution)
    names = list(solution.component_system.names)
    if values.ndim != 2 or values.shape[1] != len(names):
        return None
    times_min = np.asarray(solution.time, dtype=float) / 60.0
    series = []
    for i, name in enumerate(names):
        t, v = decimate_minmax(times_min, values[:, i], max_points)
        series.append({"name": name, "times": t, "values": v})
    return series
