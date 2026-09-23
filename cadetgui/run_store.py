from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, List, Optional

from . import __version__ as _cadetgui_version

__all__ = [
    "RunRecordState",
    "default_run_store_dir",
    "new_run_id",
    "run_output_path",
    "save_run",
    "load_run",
    "list_runs",
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
    """Local directory saved run records live in, if a caller doesn't pick one."""
    store_dir = Path.home() / ".cadetgui" / "runs"
    store_dir.mkdir(parents=True, exist_ok=True)
    return store_dir


def new_run_id() -> str:
    """Return a fresh identifier for one run, shared by its manifest and raw-output file.

    Timestamp-first so a folder's files sort chronologically and are
    recognizable at a glance rather than as opaque hex -- the trailing hex
    suffix only exists to keep two runs started in the same second unique,
    not for identification.
    """
    return f"{dt.datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"


def _manifest_path(run_id: str, store_dir: Path) -> Path:
    return store_dir / f"run_{run_id}.json"


def run_output_path(run_id: str, *, store_dir: Optional[Path] = None) -> Path:
    """Where a run's raw CADET-Core output h5 belongs, whether or not it exists yet.

    Only meaningful for the file-based simulator path (`Cadet(use_dll=False)`,
    the default) -- a run made via the CAPI (`use_dll=True`) never writes one.
    The `run_` prefix (matching its manifest) distinguishes it at a glance
    from a configuration's own `config_<hash>.h5` sitting in the same
    per-configuration folder (see `configuration_store.config_dir`).
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
    """Write one run's metadata.

    The caller is responsible for the raw output file, if any -- it must
    already sit at `run_output_path(run_id, store_dir=store_dir)` before this
    is called with `ok=True`.
    """
    store_dir = store_dir or default_run_store_dir()
    store_dir.mkdir(parents=True, exist_ok=True)
    state = RunRecordState(
        run_id=run_id,
        label=label,
        timestamp=dt.datetime.now().isoformat(),
        ok=ok,
        config_hash=config_hash,
        config_name=config_name,
        error=error,
    )
    _manifest_path(run_id, store_dir).write_text(json.dumps(asdict(state), indent=2))
    return state


def load_run(run_id: str, *, store_dir: Optional[Path] = None) -> RunRecordState:
    """Read one run's metadata by id."""
    store_dir = store_dir or default_run_store_dir()
    path = _manifest_path(run_id, store_dir)
    if not path.exists():
        raise FileNotFoundError(f"No recorded run {run_id!r} in {store_dir}.")
    return RunRecordState(**json.loads(path.read_text()))


def list_runs(*, store_dir: Optional[Path] = None) -> List[RunRecordState]:
    """List every recorded run, newest first. Silently skips unreadable manifests."""
    store_dir = store_dir or default_run_store_dir()
    paths = sorted(store_dir.glob("run_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    records = []
    for path in paths:
        try:
            records.append(RunRecordState(**json.loads(path.read_text())))
        except Exception:  # noqa: BLE001
            continue
    return records


def load_run_results(
    run: RunRecordState, process: Any, *, store_dir: Optional[Path] = None
) -> Any:
    """Reconstruct a real SimulationResults for a persisted run from its rebuilt Process.

    `process` must already reflect the same configuration the run was made
    against (e.g. via `ConfigurationWidget.import_from_store(run.config_hash)`)
    -- this only re-reads the stored solver output, it never re-simulates.
    """
    if not run.ok:
        raise ValueError(f"Run {run.run_id!r} recorded a failure, not a result.")
    output_path = run_output_path(run.run_id, store_dir=store_dir)
    if not output_path.exists():
        raise FileNotFoundError(f"No stored output for run {run.run_id!r} at {output_path}.")
    from CADETProcess.simulator import Cadet

    return Cadet().load_simulation_results(process, output_path)
