from __future__ import annotations

from pathlib import Path

__all__ = ["with_tokens"]

_TOKENS = (Path(__file__).parent / "tokens.css").read_text()


def with_tokens(*paths: Path) -> str:
    """Concatenate the shared design tokens and the given stylesheets."""
    return "\n".join([_TOKENS, *(path.read_text() for path in paths)])
