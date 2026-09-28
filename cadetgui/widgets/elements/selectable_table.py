from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import traitlets as T

from ._assets import css, esm
from .choice_field import ChoiceField

__all__ = ["SelectableTable"]

Cell = Union[str, Tuple[str, str]]


def _normalize_cell(cell: Cell) -> Dict[str, Any]:
    if isinstance(cell, str):
        return {"text": cell}
    text, chip = cell
    return {"text": text, "chip": chip}


class SelectableTable(ChoiceField):
    """A `ChoiceField` shown as a table: click or arrow-key a row to select it.

    `rows` holds one list of cells per option, matching `columns`; a cell is a string
    or `(text, kind)`, rendered as a status chip (kind: ok/warn/error/info). Without
    `rows`, each row shows its option label.
    """

    columns = T.List(T.Unicode()).tag(sync=True)
    rows = T.List(T.List(T.Dict())).tag(sync=True)
    empty_text = T.Unicode("Nothing here yet.").tag(sync=True)

    _esm = esm("selectable_table", "_field")
    _css = css("_error", "selectable_table")

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
