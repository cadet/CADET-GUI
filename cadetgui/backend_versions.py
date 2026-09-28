from __future__ import annotations

from functools import lru_cache
from importlib import metadata
from typing import Optional

import CADETProcess

from . import simulation

__all__ = ["cadet_process_version", "cadet_core_version"]


@lru_cache(maxsize=1)
def cadet_process_version() -> Optional[str]:
    """Return the installed CADET-Process version, or None if it cannot be determined."""
    version = getattr(CADETProcess, "__version__", None)
    if version:
        return str(version)
    try:
        return metadata.version("CADET-Process")
    except metadata.PackageNotFoundError:
        return None


@lru_cache(maxsize=1)
def cadet_core_version() -> Optional[str]:
    """Return the CADET-Core version `run_process` uses, or None if unavailable.

    Cached: reading it runs `cadet-cli --version`.
    """
    try:
        version = simulation.Cadet().version
    except Exception:  # noqa: BLE001
        return None
    return str(version) if version else None
