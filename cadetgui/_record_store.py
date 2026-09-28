from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import List, Type, TypeVar

__all__ = [
    "user_store_dir",
    "new_record_id",
    "save_record",
    "load_record",
    "list_records",
    "delete_record",
]

T = TypeVar("T")


def user_store_dir(name: str) -> Path:
    """Return `~/.cadetgui/<name>`, created on demand."""
    store_dir = Path.home() / ".cadetgui" / name
    store_dir.mkdir(parents=True, exist_ok=True)
    return store_dir


def new_record_id() -> str:
    """Return a fresh id: a sortable timestamp plus a short suffix for same-second uniqueness."""
    return f"{dt.datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"


def _manifest_path(prefix: str, id_: str, store_dir: Path) -> Path:
    return store_dir / f"{prefix}_{id_}.json"


def save_record(prefix: str, id_: str, state: object, store_dir: Path) -> None:
    """Write one dataclass instance as `<store_dir>/<prefix>_<id_>.json`."""
    store_dir.mkdir(parents=True, exist_ok=True)
    _manifest_path(prefix, id_, store_dir).write_text(json.dumps(asdict(state), indent=2))


def load_record(prefix: str, id_: str, cls: Type[T], store_dir: Path) -> T:
    """Read one record by id, raising `FileNotFoundError` if it isn't there."""
    path = _manifest_path(prefix, id_, store_dir)
    if not path.exists():
        raise FileNotFoundError(f"No recorded {prefix} {id_!r} in {store_dir}.")
    return cls(**json.loads(path.read_text()))


def list_records(prefix: str, cls: Type[T], store_dir: Path) -> List[T]:
    """List every `<prefix>_*` record, newest first, skipping unreadable manifests."""
    paths = sorted(
        store_dir.glob(f"{prefix}_*.json"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    records = []
    for path in paths:
        try:
            records.append(cls(**json.loads(path.read_text())))
        except (ValueError, TypeError):
            continue
    return records


def delete_record(prefix: str, id_: str, store_dir: Path) -> bool:
    """Remove one record's manifest; return whether it existed."""
    path = _manifest_path(prefix, id_, store_dir)
    if not path.exists():
        return False
    path.unlink()
    return True
