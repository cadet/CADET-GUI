from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cadet import H5

from . import __version__ as _cadetgui_version

__all__ = [
    "ConfigurationState",
    "compute_hash",
    "default_store_dir",
    "save_h5",
    "load_h5",
    "save_to_store",
    "load_from_store",
]


@dataclass(frozen=True)
class ConfigurationState:
    """The hashed, JSON-safe payload needed to reconstruct a ConfigurationWidget."""

    components: List[str]
    column_key: str
    binding_key: str
    template_key: str
    multiplex_state: Dict[str, bool] = field(default_factory=dict)
    show_optional_column: bool = False
    show_optional_binding: bool = False
    column_values: Dict[str, Any] = field(default_factory=dict)
    binding_values: Dict[str, Any] = field(default_factory=dict)
    model_values: Dict[str, Any] = field(default_factory=dict)


def compute_hash(state: ConfigurationState) -> str:
    """Content-addressed fingerprint of a configuration (the name is not hashed)."""
    payload = json.dumps(asdict(state), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def default_store_dir() -> Path:
    """Local directory saved/imported-by-hash configurations live in."""
    store_dir = Path.home() / ".cadetgui" / "configurations"
    store_dir.mkdir(parents=True, exist_ok=True)
    return store_dir


def _decode_h5_leaf(value: Any) -> Any:
    """Coerce one h5py/numpy/bytes leaf back to a plain JSON-safe Python type."""
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if isinstance(value, dict):
        return {k: _decode_h5_leaf(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_decode_h5_leaf(v) for v in value]
    if isinstance(value, bytes):
        return value.decode()
    if hasattr(value, "tolist"):  # numpy scalar or ndarray
        return _decode_h5_leaf(value.tolist())
    return value


def save_h5(
    state: ConfigurationState,
    name: str,
    path: "Path | str",
    *,
    process: Any = None,
) -> None:
    """Write a configuration to `path` as h5.

    Always writes a `cadetgui` group holding the full GUI-reconstruction
    state (the only thing `load_h5` reads back). When `process` is given,
    also embeds the real CADET-Core solver config under the same file
    (best-effort -- a missing/unlocatable CADET-Core install must not block
    saving the GUI state, which never depends on it).
    """
    h5 = H5()
    if process is not None:
        try:
            from CADETProcess.simulator import Cadet

            h5.root.update(Cadet().get_process_config(process))
        except Exception:  # noqa: BLE001
            pass

    h5.root.cadetgui = {
        "name": name,
        "hash": compute_hash(state),
        "created": dt.datetime.now().isoformat(),
        "cadetgui_version": _cadetgui_version,
        "state": asdict(state),
    }
    h5.filename = str(path)
    h5.save()


def load_h5(path: "Path | str") -> Tuple[str, ConfigurationState]:
    """Read a configuration previously written by `save_h5`.

    Returns (name, state). Raises ValueError if `path` has no `cadetgui`
    group (e.g. a plain CADET-Core h5 file).
    """
    h5 = H5()
    h5.filename = str(path)
    h5.load_from_file()

    root = _decode_h5_leaf(h5.root)
    gui = root.get("cadetgui")
    if not gui:
        raise ValueError(f"{path} has no 'cadetgui' group -- not a saved configuration.")

    payload = gui["state"]
    state = ConfigurationState(
        components=payload["components"],
        column_key=payload["column_key"],
        binding_key=payload["binding_key"],
        template_key=payload["template_key"],
        multiplex_state=payload.get("multiplex_state", {}),
        show_optional_column=payload.get("show_optional_column", False),
        show_optional_binding=payload.get("show_optional_binding", False),
        column_values=payload.get("column_values", {}),
        binding_values=payload.get("binding_values", {}),
        model_values=payload.get("model_values", {}),
    )
    return gui["name"], state


def save_to_store(
    state: ConfigurationState,
    name: str,
    *,
    process: Any = None,
    store_dir: Optional[Path] = None,
) -> Path:
    """Save to the local configuration store, keyed by content hash. Returns the path."""
    store_dir = store_dir or default_store_dir()
    store_dir.mkdir(parents=True, exist_ok=True)
    path = store_dir / f"{compute_hash(state)}.h5"
    save_h5(state, name, path, process=process)
    return path


def load_from_store(
    hash_: str, *, store_dir: Optional[Path] = None
) -> Tuple[str, ConfigurationState]:
    """Load a configuration from the local store by its hash."""
    store_dir = store_dir or default_store_dir()
    path = store_dir / f"{hash_}.h5"
    if not path.exists():
        raise FileNotFoundError(f"No saved configuration with hash {hash_!r} in {store_dir}.")
    return load_h5(path)
