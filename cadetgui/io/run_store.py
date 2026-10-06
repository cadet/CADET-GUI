from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from .. import __version__ as _cadetgui_version
from ._record_store import (
    delete_record,
    list_records,
    load_record,
    new_record_id,
    save_record,
    user_store_dir,
)

__all__ = [
    "RunRecordState",
    "default_run_store_dir",
    "new_run_id",
    "run_output_path",
    "save_run",
    "load_run",
    "list_runs",
    "delete_run",
    "load_run_results",
]


@dataclass(frozen=True)
class RunRecordState:
    """Persisted run metadata. The raw CADET-Core output (if any) is a sibling `run_<run_id>.h5`."""

    run_id: str
    label: str
    timestamp: str
    ok: bool
    config_hash: Optional[str] = None
    config_name: Optional[str] = None
    error: Optional[str] = None
    cadetgui_version: str = _cadetgui_version


def default_run_store_dir() -> Path:
    """Local directory run records live in when a caller doesn't pick one."""
    return user_store_dir("runs")


def new_run_id() -> str:
    """Return a fresh id shared by a run's manifest and raw-output file."""
    return new_record_id()


def run_output_path(run_id: str, *, store_dir: Optional[Path] = None) -> Path:
    """Where a run's raw CADET-Core output h5 belongs, whether or not it exists yet.

    Only the file-based simulator writes one; the `run_` prefix keeps it apart from
    a `config_<hash>.h5` in the same folder.
    """
    store_dir = store_dir or default_run_store_dir()
    return store_dir / f"run_{run_id}.h5"


def save_run(
    run_id: str,
    label: str,
    *,
    ok: bool,
    config_hash: Optional[str] = None,
    config_name: Optional[str] = None,
    error: Optional[str] = None,
    store_dir: Optional[Path] = None,
) -> RunRecordState:
    """Write one run's metadata; the caller places any raw output at `run_output_path` first."""
    store_dir = store_dir or default_run_store_dir()
    state = RunRecordState(
        run_id=run_id,
        label=label,
        timestamp=dt.datetime.now().isoformat(),
        ok=ok,
        config_hash=config_hash,
        config_name=config_name,
        error=error,
    )
    save_record("run", run_id, state, store_dir)
    return state


def load_run(run_id: str, *, store_dir: Optional[Path] = None) -> RunRecordState:
    """Read one run's metadata by id."""
    store_dir = store_dir or default_run_store_dir()
    return load_record("run", run_id, RunRecordState, store_dir)


def list_runs(*, store_dir: Optional[Path] = None) -> List[RunRecordState]:
    """List every recorded run, newest first, skipping unreadable manifests."""
    store_dir = store_dir or default_run_store_dir()
    return list_records("run", RunRecordState, store_dir)


def delete_run(run_id: str, *, store_dir: Optional[Path] = None) -> bool:
    """Delete one run's manifest and raw output file; return whether anything was removed."""
    if not run_id or Path(run_id).name != run_id:
        raise ValueError(f"Invalid run id {run_id!r}.")
    store_dir = store_dir or default_run_store_dir()
    removed = delete_record("run", run_id, store_dir)
    output_path = run_output_path(run_id, store_dir=store_dir)
    if output_path.exists():
        output_path.unlink()
        removed = True
    return removed


def load_run_results(
    run: RunRecordState, process: Any, *, store_dir: Optional[Path] = None
) -> Any:
    """Reload a persisted run's SimulationResults; `process` must match the run's configuration."""
    if not run.ok:
        raise ValueError(f"Run {run.run_id!r} recorded a failure, not a result.")
    output_path = run_output_path(run.run_id, store_dir=store_dir)
    if not output_path.exists():
        raise FileNotFoundError(f"No stored output for run {run.run_id!r} at {output_path}.")
    from CADETProcess.simulator import Cadet

    return Cadet().load_simulation_results(process, output_path)
