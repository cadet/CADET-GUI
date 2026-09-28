from __future__ import annotations

import io
from typing import Any

import ipywidgets as W

__all__ = ["new_figure", "display_figure"]


def new_figure(**kwargs: Any) -> Any:
    """Build a matplotlib Figure on its own Agg canvas, bypassing `pyplot`.

    `pyplot` state is global and not thread-safe, so background-thread rendering must
    pass the resulting axes to any plotting call (e.g. `solution.plot(ax=...)`).
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(**kwargs)
    FigureCanvasAgg(fig)
    return fig


def display_figure(output: W.Image, fig: Any, *, dpi: int = 150) -> None:
    """Render `fig` into `output.value` as PNG bytes and reveal `output`.

    Assigns the trait directly, which is safe from a background thread (unlike
    `Output.display()`). Leave the image's CSS width unset so `dpi` sets its size.
    """
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    output.value = buf.getvalue()
    output.layout.display = ""
