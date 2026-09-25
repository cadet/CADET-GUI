from __future__ import annotations

from functools import lru_cache
from importlib import metadata
from typing import Optional

__all__ = ["cadet_process_version", "cadet_core_version"]


@lru_cache(maxsize=1)
def cadet_process_version() -> Optional[str]:
    """Installed CADET-Process version, or None if it cannot be determined."""
    try:
        import CADETProcess

        version = getattr(CADETProcess, "__version__", None)
        if version:
            return str(version)
    except Exception:  # noqa: BLE001
        pass
    try:
        return metadata.version("CADET-Process")
    except Exception:  # noqa: BLE001
        return None


@lru_cache(maxsize=1)
def cadet_core_version() -> Optional[str]:
    """CADET-Core version of the simulator `run_process` uses, or None if unavailable.

    Queried once (it runs `cadet-cli --version`) and cached.
    """
    try:
        from . import simulation

        if simulation.Cadet is None:
            return None
        version = simulation.Cadet().version
        return str(version) if version else None
    except Exception:  # noqa: BLE001
        return None
