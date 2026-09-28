from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from . import __version__ as _cadetgui_version
from ._record_store import list_records, new_record_id, save_record, user_store_dir

__all__ = [
    "ParameterPushRecordState",
    "default_parameter_history_store_dir",
    "new_push_id",
    "save_push",
    "list_pushes",
]


@dataclass(frozen=True)
class ParameterPushRecordState:
    """Provenance of one "Push to Configuration": what produced `values`, and where they went."""

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
    """Local directory parameter-push records live in when a caller doesn't pick one."""
    return user_store_dir("parameter_history")


def new_push_id() -> str:
    """Return a fresh id for one push."""
    return new_record_id()


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
    """Write one push record."""
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
    """List every recorded push, newest first, skipping unreadable manifests."""
    store_dir = store_dir or default_parameter_history_store_dir()
    return list_records("push", ParameterPushRecordState, store_dir)
