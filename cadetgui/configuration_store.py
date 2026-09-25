from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cadet import H5

from . import __version__ as _cadetgui_version

__all__ = [
    "InstrumentState",
    "ConfigurationState",
    "compute_hash",
    "default_store_dir",
    "safe_config_dirname",
    "config_dir",
    "runs_dir",
    "save_h5",
    "load_h5",
    "save_to_store",
    "load_from_store",
    "list_store",
]


@dataclass(frozen=True)
class InstrumentState:
    """The hashed, JSON-safe payload needed to reconstruct an InstrumentWidget.

    Topology only -- component names and column/binding *type* now live
    directly on `ConfigurationState` (its own pickers own that choice, see
    ARCHITECTURE.md's "instrument attachment optional" section), not nested
    in here.
    """

    include_sample_loop: bool = False
    sample_loop_volume: float = 50e-9
    sample_loop_diameter_auto: bool = True
    sample_loop_diameter: float = 0.75e-3
    bypass_units: List[str] = field(default_factory=list)
    # Per-unit parameter values for the mixer/tubing dead-volume units
    # (`{"mixer": {"init_liquid_volume": ...}, "tubing_pre_column": {...}, ...}`),
    # keyed by unit name -- see ARCHITECTURE.md's "Units In Flow Path" section.
    unit_values: Dict[str, Dict[str, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class ConfigurationState:
    """The hashed, JSON-safe payload needed to reconstruct a ConfigurationWidget.

    `instrument` is `None` when no InstrumentWidget was bound -- the
    configuration was a standalone bare-column simulation.
    """

    components: List[str]
    column_key: str
    binding_key: str
    template_key: str
    instrument: Optional[InstrumentState] = None
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


_UNSAFE_DIRNAME_CHARS = re.compile(r"[^\w\-.]")


def safe_config_dirname(name: str) -> str:
    """Filesystem-safe subfolder name for a configuration -- whitespace becomes
    underscores, anything else unsafe in a folder name is dropped.
    """
    cleaned = _UNSAFE_DIRNAME_CHARS.sub("", name.strip().replace(" ", "_"))
    return cleaned or "unnamed"


def config_dir(name: str, *, store_dir: Optional[Path] = None) -> Path:
    """The per-configuration subfolder one configuration's own save file, and
    any run results saved alongside it, live under. Created on demand.
    """
    store_dir = store_dir or default_store_dir()
    path = store_dir / safe_config_dirname(name)
    path.mkdir(parents=True, exist_ok=True)
    return path


def runs_dir(name: str, *, store_dir: Optional[Path] = None) -> Path:
    """Return the `runs` subfolder of a configuration's folder, created on demand.

    Run manifests and raw outputs that older versions left directly in the
    configuration's folder are moved in here once, so existing runs stay listed.
    """
    folder = config_dir(name, store_dir=store_dir)
    runs = folder / "runs"
    runs.mkdir(exist_ok=True)
    for legacy in [*folder.glob("run_*.json"), *folder.glob("run_*.h5")]:
        target = runs / legacy.name
        if not target.exists():
            legacy.rename(target)
    return runs


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

    # HDF5 has no NoneType -- `instrument=None` (standalone config, no
    # InstrumentWidget bound) is stored as an empty dict instead; load_h5
    # treats an empty/missing "instrument" the same way.
    payload = asdict(state)
    if payload.get("instrument") is None:
        payload["instrument"] = {}

    h5.root.cadetgui = {
        "name": name,
        "hash": compute_hash(state),
        "created": dt.datetime.now().isoformat(),
        "cadetgui_version": _cadetgui_version,
        "state": payload,
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
    instrument_payload = payload.get("instrument") or {}
    instrument = (
        InstrumentState(
            include_sample_loop=instrument_payload.get("include_sample_loop", True),
            sample_loop_volume=instrument_payload.get("sample_loop_volume", 50e-9),
            sample_loop_diameter_auto=instrument_payload.get("sample_loop_diameter_auto", True),
            sample_loop_diameter=instrument_payload.get("sample_loop_diameter", 0.75e-3),
            bypass_units=list(instrument_payload.get("bypass_units", [])),
            unit_values={
                k: dict(v) for k, v in instrument_payload.get("unit_values", {}).items()
            },
        )
        if instrument_payload
        else None
    )
    state = ConfigurationState(
        components=payload["components"],
        column_key=payload["column_key"],
        binding_key=payload["binding_key"],
        template_key=payload["template_key"],
        instrument=instrument,
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
    """Save to the local configuration store, under a subfolder for `name`.

    Content hash stays the true identity, not the folder: renaming a saved
    configuration must not change it, and two identical configurations under
    different names still collide to one file (ARCHITECTURE.md). So if this
    exact hash was already saved under some other name, that existing
    subfolder/file is reused (its metadata updated) instead of creating a
    duplicate copy under the new name -- the folder simply keeps whichever
    name first saved that content. Returns the path.

    The `config_` filename prefix distinguishes it at a glance from a run's
    own `run_<run_id>.h5` raw solver output, which can live in the same
    per-configuration folder (see `run_store.run_output_path`).
    """
    store_dir = store_dir or default_store_dir()
    store_dir.mkdir(parents=True, exist_ok=True)
    hash_ = compute_hash(state)
    existing = next(store_dir.glob(f"*/config_{hash_}.h5"), None)
    path = (
        existing if existing is not None
        else config_dir(name, store_dir=store_dir) / f"config_{hash_}.h5"
    )
    save_h5(state, name, path, process=process)
    return path


def load_from_store(
    hash_: str, *, store_dir: Optional[Path] = None
) -> Tuple[str, ConfigurationState]:
    """Load a configuration from the local store by its hash.

    Only the hash is known to the caller (a run's `config_hash`, or a hash
    pasted by hand) -- not which name's subfolder it lives under -- so every
    configuration subfolder is searched.
    """
    store_dir = store_dir or default_store_dir()
    path = next(store_dir.glob(f"*/config_{hash_}.h5"), None)
    if path is None:
        raise FileNotFoundError(f"No saved configuration with hash {hash_!r} in {store_dir}.")
    return load_h5(path)


def list_store(*, store_dir: Optional[Path] = None) -> List[Tuple[str, str]]:
    """List every saved configuration as (name, hash) pairs, newest first.

    Silently skips any file that isn't a valid saved configuration (e.g. a
    plain CADET-Core h5 someone dropped into a configuration's subfolder by
    hand). The `config_` glob already excludes a run's own raw solver-output
    h5 sitting alongside it (see `run_store.run_output_path`'s `run_` prefix).
    """
    store_dir = store_dir or default_store_dir()
    paths = sorted(store_dir.glob("*/config_*.h5"), key=lambda p: p.stat().st_mtime, reverse=True)
    entries = []
    for path in paths:
        try:
            name, _ = load_h5(path)
        except Exception:  # noqa: BLE001
            continue
        entries.append((name, path.stem.removeprefix("config_")))
    return entries
