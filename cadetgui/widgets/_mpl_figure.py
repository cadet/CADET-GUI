from __future__ import annotations

import io
from typing import Any

import ipywidgets as W

__all__ = ["new_figure", "display_figure"]


def new_figure(**kwargs: Any) -> Any:
    """Build a matplotlib Figure with its own Agg canvas -- never touches `pyplot`.

    For rendering on a background thread: `pyplot`'s figure/backend state is
    global and generally not thread-safe (confirmed: a plain `plt.
    subplots()` call from a non-main thread crashes under an interactive
    backend like TkAgg, e.g. `RuntimeError: main thread is not in main
    loop`). Building the Figure directly and attaching `FigureCanvasAgg`
    sidesteps `pyplot` (and therefore the active backend) entirely --
    works the same regardless of thread or ambient backend. Must always
    be paired with passing the resulting Axes into anything that would
    otherwise create its own figure (e.g. `solution.plot(ax=...)`, never
    bare `solution.plot()` -- the latter calls `plt.subplots()` internally).
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(**kwargs)
    FigureCanvasAgg(fig)
    return fig


def display_figure(output: W.Image, fig: Any, *, dpi: int = 150) -> None:
    """Render `fig` into `output.value` as PNG bytes and reveal `output`.

    A direct trait assignment, not `Output`'s capture-based `display()` --
    confirmed (real Jupyter kernel, not just a sandbox) that the latter does
    not reliably route from a background thread, while a plain trait update
    (like `Image.value`) does, from any thread. No CSS width/max-width should
    be set on `output` by the caller -- displayed size is then exactly the
    PNG's own pixel dimensions, so `dpi` controls both sharpness and how big
    it actually appears.
    """
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    output.value = buf.getvalue()
    output.layout.display = ""
