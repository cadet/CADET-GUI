from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from . import __version__ as _cadetgui_version
from ._record_store import list_records, save_record

__all__ = [
    "ParameterPushRecordState",
    "default_parameter_history_store_dir",
    "new_push_id",
    "save_push",
    "list_pushes",
]


@dataclass(frozen=True)
class ParameterPushRecordState:
    """Persisted record of one "Push to Configuration" -- the provenance of a fit.

    Answers "which experiment(s) determined this parameter, with what
    result" -- `stage`/`dataset_labels` say what produced `values`,
    `objective`/`optimizer_name` say how well and with what, `config_hash`
    anchors it to the configuration it was pushed into (same convention as
    `run_store.RunRecordState.config_hash`).
    """

    push_id: str
    stage: str
    timestamp: str
    values: Dict[str, float]
    dataset_labels: List[str] = field(default_factory=list)
    optimizer_name: Optional[str] = None
    objective: Optional[float] = None
    config_hash: Optional[str] = None
    config_name: Optional[str] = None
    cadetgui_version: str = _cadetgui_version


def default_parameter_history_store_dir() -> Path:
    """Local directory saved parameter-push records live in, if a caller doesn't pick one."""
    store_dir = Path.home() / ".cadetgui" / "parameter_history"
    store_dir.mkdir(parents=True, exist_ok=True)
    return store_dir


def new_push_id() -> str:
    """Return a fresh identifier for one push -- same shape as `run_store.new_run_id`."""
    return f"{dt.datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"


def save_push(
    push_id: str,
    stage: str,
    values: Dict[str, float],
    *,
    dataset_labels: Optional[List[str]] = None,
    optimizer_name: Optional[str] = None,
    objective: Optional[float] = None,
    config_hash: Optional[str] = None,
    config_name: Optional[str] = None,
    store_dir: Optional[Path] = None,
) -> ParameterPushRecordState:
    """Write one push's metadata."""
    store_dir = store_dir or default_parameter_history_store_dir()
    state = ParameterPushRecordState(
        push_id=push_id,
        stage=stage,
        timestamp=dt.datetime.now().isoformat(),
        values=dict(values),
        dataset_labels=list(dataset_labels or []),
        optimizer_name=optimizer_name,
        objective=objective,
        config_hash=config_hash,
        config_name=config_name,
    )
    save_record("push", push_id, state, store_dir)
    return state


def list_pushes(*, store_dir: Optional[Path] = None) -> List[ParameterPushRecordState]:
    """List every recorded push, newest first. Silently skips unreadable manifests."""
    store_dir = store_dir or default_parameter_history_store_dir()
    return list_records("push", ParameterPushRecordState, store_dir)
