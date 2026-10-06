from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import numpy as np

from ...io import configuration_store


def save_signal_outputs(
    result: Any,
    targets: Sequence[tuple[str, str]],
    results_dir: Path,
    stem_prefix: str,
    *,
    plots: bool,
    csv: bool,
) -> int:
    """Write a PNG plot and/or CSV of each `(unit, port)` signal into `results_dir`.

    Returns the number of files written.
    """
    import matplotlib.pyplot as plt

    results_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    for unit, port in targets:
        solution = result.solution[unit][port]
        stem = f"{stem_prefix}_{configuration_store.safe_config_dirname(f'{unit}_{port}')}"
        if plots:
            fig, _ax = solution.plot()
            fig.savefig(results_dir / f"{stem}.png", dpi=150, bbox_inches="tight")
            plt.close(fig)
            saved += 1
        if csv:
            data = np.column_stack([solution.time, solution.solution])
            header = "time," + ",".join(solution.component_system.names)
            np.savetxt(
                results_dir / f"{stem}.csv", data, delimiter=",", header=header, comments=""
            )
            saved += 1
    return saved
