from __future__ import annotations

from pathlib import Path

__all__ = ["with_tokens"]

_TOKENS = (Path(__file__).parent / "tokens.css").read_text()


def with_tokens(path: Path) -> str:
    """CSS text of `path` preceded by the shared design tokens (see tokens.css)."""
    return f"{_TOKENS}\n{path.read_text()}"
