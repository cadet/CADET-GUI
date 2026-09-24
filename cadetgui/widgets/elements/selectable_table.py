from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import traitlets as T

from .._tokens import with_tokens
from .choice_field import ChoiceField

__all__ = ["SelectableTable"]

_DIR = Path(__file__).parent

Cell = Union[str, Tuple[str, str]]


def _normalize_cell(cell: Cell) -> Dict[str, Any]:
    if isinstance(cell, str):
        return {"text": cell}
    text, chip = cell
    return {"text": text, "chip": chip}


class SelectableTable(ChoiceField):
    """A `ChoiceField` shown as a table: click or arrow-key a row to select it.

    Same contract as `ChoiceField` (`options` are `(label, value)` pairs,
    `value`/`selected_index`/`set_options` behave identically), so it drops in
    wherever a dropdown picker is used. `rows` adds what the dropdown can't
    show: one list of cells per option, matching `columns`. A cell is a plain
    string or `(text, kind)`, rendered as a status chip (`kind` is one of
    ok/warn/error/info). Without `rows`, each row shows just its option label.
    """

    columns = T.List(T.Unicode()).tag(sync=True)
    rows = T.List(T.List(T.Dict())).tag(sync=True)
    empty_text = T.Unicode("Nothing here yet.").tag(sync=True)

    _esm = _DIR / "selectable_table.js"
    _css = with_tokens(_DIR / "selectable_table.css")

    def __init__(
        self,
        *,
        columns: Sequence[str] = (),
        rows: Optional[Sequence[Sequence[Cell]]] = None,
        empty_text: str = "Nothing here yet.",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.columns = list(columns)
        self.empty_text = empty_text
        self.rows = self._rows_for(rows, self._options)

    @staticmethod
    def _rows_for(
        rows: Optional[Sequence[Sequence[Cell]]], options: Sequence[Tuple[str, Any]]
    ) -> List[List[Dict[str, Any]]]:
        if rows is None:
            rows = [[label] for label, _ in options]
        if len(rows) != len(options):
            raise ValueError(f"Got {len(rows)} rows for {len(options)} options")
        return [[_normalize_cell(c) for c in row] for row in rows]

    def set_options(
        self,
        options: Sequence[Tuple[str, Any]],
        *,
        rows: Optional[Sequence[Sequence[Cell]]] = None,
        keep_value: bool = True,
        select_none: bool = False,
    ) -> None:
        """Replace the options and their table rows; see `ChoiceField.set_options`."""
        self.rows = self._rows_for(rows, options)
        super().set_options(options, keep_value=keep_value, select_none=select_none)
