from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import List, Type, TypeVar

__all__ = ["save_record", "load_record", "list_records", "delete_record"]

T = TypeVar("T")


def _manifest_path(prefix: str, id_: str, store_dir: Path) -> Path:
    return store_dir / f"{prefix}_{id_}.json"


def save_record(prefix: str, id_: str, state: object, store_dir: Path) -> None:
    """Write one dataclass instance as `<store_dir>/<prefix>_<id_>.json`.

    Shared by `cadetgui.run_store` and `cadetgui.parameter_history_store` --
    both are the same shape (one JSON manifest per record, a `<prefix>_*`
    glob to list them, newest-by-mtime first) over a different dataclass.
    """
    store_dir.mkdir(parents=True, exist_ok=True)
    _manifest_path(prefix, id_, store_dir).write_text(json.dumps(asdict(state), indent=2))


def load_record(prefix: str, id_: str, cls: Type[T], store_dir: Path) -> T:
    """Read one record by id, raising `FileNotFoundError` if it isn't there."""
    path = _manifest_path(prefix, id_, store_dir)
    if not path.exists():
        raise FileNotFoundError(f"No recorded {prefix} {id_!r} in {store_dir}.")
    return cls(**json.loads(path.read_text()))


def list_records(prefix: str, cls: Type[T], store_dir: Path) -> List[T]:
    """List every recorded `<prefix>_*` manifest, newest first. Skips unreadable ones."""
    paths = sorted(
        store_dir.glob(f"{prefix}_*.json"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    records = []
    for path in paths:
        try:
            records.append(cls(**json.loads(path.read_text())))
        except Exception:  # noqa: BLE001
            continue
    return records


def delete_record(prefix: str, id_: str, store_dir: Path) -> bool:
    """Remove one record's manifest; return whether it existed."""
    path = _manifest_path(prefix, id_, store_dir)
    if not path.exists():
        return False
    path.unlink()
    return True
