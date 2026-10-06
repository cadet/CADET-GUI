"""Import experimental chromatography runs: generic header CSVs and Äkta/Unicorn exports.

Headless (no ipywidgets); `cadetgui/widgets/composite/data_import.py` is the UI over this.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Literal, Optional, Sequence, Tuple

import numpy as np

if TYPE_CHECKING:
    from CADETProcess.reference import ReferenceIO

__all__ = [
    "Channel",
    "ExperimentalRun",
    "ExperimentalDataset",
    "ColumnRole",
    "XBasis",
    "detect_column_roles",
    "is_akta_format",
    "read_headers",
    "read_generic_csv",
    "read_akta_csv",
    "read_experimental_csv",
    "write_experimental_csv",
    "to_time",
    "to_reference",
]

XBasis = Literal["time", "volume"]
ColumnRole = Literal["time_s", "time_min", "volume_ml", "signal", "skip"]

_AKTA_HEADER_ROWS = 3


@dataclass
class Channel:
    """One signal trace: `x` (time or volume) paired with `values`, both 1D."""

    name: str
    x: np.ndarray
    values: np.ndarray
    unit: Optional[str] = None


@dataclass
class ExperimentalRun:
    """One imported run: named channels sharing an x-basis, plus text event markers."""

    label: str
    channels: Dict[str, Channel]
    x_basis: XBasis
    x_unit: str
    markers: List[Tuple[float, str]] = field(default_factory=list)


@dataclass
class ExperimentalDataset:
    """One imported signal, time already normalized to minutes.

    Kept for backward compatibility with widgets that only need `label`/`time_min`/
    `signal`; `run`/`channel` identify the source `ExperimentalRun`/`Channel` when set.
    """

    label: str
    time_min: np.ndarray
    signal: np.ndarray
    run: Optional[ExperimentalRun] = None
    channel: Optional[str] = None


def _decode(content: bytes) -> str:
    """Decode a CSV export, handling Unicorn's utf-16 (BOM) and latin-1 exports."""
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        return content.decode("utf-16")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("latin-1")


_DECIMAL_COMMA = re.compile(r"^\s*[-+]?\d*,\d+(?:[eE][-+]?\d+)?\s*$")


def _rows(content: bytes) -> List[List[str]]:
    """Split a delimited text export into rows of cells.

    The delimiter is a semicolon or a tab when most of the last lines have one, else a
    comma; with semicolons or tabs a decimal comma (`1,5`) is read as a point.
    """
    text = _decode(content)
    tail = [line for line in text.splitlines() if line.strip()][-50:]
    delimiter = next(
        (d for d in (";", "\t") if 2 * sum(d in line for line in tail) > len(tail)), ","
    )
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if delimiter != ",":
        rows = [[c.replace(",", ".") if _DECIMAL_COMMA.match(c) else c for c in row]
                for row in rows]
    return rows


def _is_data_row(row: Sequence[str]) -> bool:
    cells = [c for c in row if c.strip()]
    numbers = sum(_is_number(c) for c in cells)
    return numbers >= 2 and 2 * numbers >= len(cells)


def _table(rows: List[List[str]]) -> Tuple[List[str], List[List[str]]]:
    """Return the header row and the data rows, skipping metadata lines above the header."""
    start = next((i for i, row in enumerate(rows) if _is_data_row(row)), None)
    if start is None or start == 0:
        raise ValueError("No header row followed by numeric data found.")
    return rows[start - 1], rows[start:]


def _is_number(cell: str) -> bool:
    cell = cell.strip()
    if cell == "":
        return True
    try:
        float(cell)
        return True
    except ValueError:
        return False


def detect_column_roles(headers: Sequence[str]) -> List[ColumnRole]:
    """Guess a role per column from its header text; unmatched columns become signal.

    Mirrors gosilizwo's `guessColumnRoles`: a header naming volume (`volume`, `ml`,
    `m3`/`m³`) is preferred as the x-axis; otherwise a header naming `time` is used, in
    `min` when the header says so and `s` otherwise, falling back to the first column.
    """
    lower = [h.lower() for h in headers]

    def _is_volume(h: str) -> bool:
        return any(k in h for k in ("volume", "m3", "m³", "ml"))

    volume_index = next((i for i, h in enumerate(lower) if _is_volume(h)), None)
    if volume_index is not None:
        x_index: int = volume_index
        x_role: ColumnRole = "volume_ml"
    else:
        time_index = next((i for i, h in enumerate(lower) if "time" in h), 0)
        x_index = time_index
        x_role = "time_min" if "min" in lower[time_index] else "time_s"

    roles: List[ColumnRole] = ["signal"] * len(headers)
    roles[x_index] = x_role
    return roles


def is_akta_format(content: bytes) -> bool:
    """Detect an Äkta/Unicorn export (3 header rows, channel names).

    Distinguishing signal: a generic CSV's second line is a data row (all-numeric); an
    Äkta export's second line is the channel-name row, which is not.
    """
    rows = _rows(content)
    if len(rows) < _AKTA_HEADER_ROWS + 1:
        return False
    name_row, unit_row = rows[1], rows[2]
    return (
        len(name_row) >= 2 and any(not _is_number(cell) for cell in name_row)
        and bool(unit_row) and unit_row[0].strip().lower() in ("ml", "min")
        and _is_number(rows[3][0] if rows[3] else "x")
    )


def read_headers(content: bytes) -> List[str]:
    """Return the header row of a CSV (the row above the first numeric row), or []."""
    try:
        return _table(_rows(content))[0]
    except ValueError:
        return []


def read_generic_csv(
    content: bytes,
    label: str,
    roles: Optional[Sequence[ColumnRole]] = None,
) -> ExperimentalRun:
    """Parse a header-row CSV (one x column + N signal columns) into an `ExperimentalRun`.

    Comma, semicolon or tab separated; decimal commas and metadata lines above the
    header row are handled (see `_rows`, `_table`).

    `roles` assigns exactly one x column (`"time_s"`/`"time_min"`/`"volume_ml"`) and any
    number of `"signal"`/`"skip"` columns, one entry per CSV column; defaults to
    `detect_column_roles(headers)`.
    """
    rows = _rows(content)
    if not rows:
        raise ValueError("Empty CSV.")
    headers, data = _table(rows)
    if roles is None:
        roles = detect_column_roles(headers)
    if len(roles) != len(headers):
        raise ValueError("roles must have one entry per column.")

    columns: List[List[float]] = [[] for _ in headers]
    for row in data:
        if len(row) < len(headers):
            continue
        try:
            values = [float(v) for v in row[: len(headers)]]
        except ValueError:
            continue
        for i, v in enumerate(values):
            columns[i].append(v)

    arrays = [np.array(col) for col in columns]

    x_indices = [i for i, r in enumerate(roles) if r in ("time_s", "time_min", "volume_ml")]
    if len(x_indices) != 1:
        raise ValueError("Exactly one column must be assigned time or volume.")
    x_index = x_indices[0]
    x_role = roles[x_index]

    if x_role == "volume_ml":
        x_basis: XBasis = "volume"
        x_unit = "mL"
        x = arrays[x_index]
    else:
        x_basis = "time"
        x_unit = "s"
        x = arrays[x_index] * 60.0 if x_role == "time_min" else arrays[x_index]

    channels = {
        (headers[i].strip() or f"column {i}"): Channel(
            name=headers[i].strip() or f"column {i}", x=x, values=arrays[i]
        )
        for i, r in enumerate(roles)
        if r == "signal"
    }
    if not channels:
        raise ValueError("At least one signal column is required.")

    return ExperimentalRun(label=label, channels=channels, x_basis=x_basis, x_unit=x_unit)


def _to_float_array(values: Sequence[str]) -> np.ndarray:
    out = np.full(len(values), np.nan)
    for i, v in enumerate(values):
        try:
            out[i] = float(v)
        except ValueError:
            pass
    return out


def _text_markers(volume: np.ndarray, text: Sequence[str], prefix: str) -> List[Tuple[float, str]]:
    markers = []
    for v, t in zip(volume, text):
        t = t.strip()
        if np.isnan(v) or not t.startswith(prefix) or t == prefix:
            continue
        markers.append((float(v), t))
    return markers


def read_akta_csv(content: bytes, label: str) -> ExperimentalRun:
    """Parse an Äkta/Unicorn export.

    3 header rows, each channel an independent `(volume, value)` column pair. Text
    channels (`Run Log`, `Fraction`) become markers instead of `Channel`s; `Run Log`
    keeps only entries starting with `"Phase "`.
    """
    rows = _rows(content)
    if len(rows) <= _AKTA_HEADER_ROWS:
        raise ValueError("Not an Äkta-style export.")

    name_row = rows[1]
    names = [name_row[i].strip() for i in range(0, len(name_row), 2) if name_row[i].strip()]

    data_rows = rows[_AKTA_HEADER_ROWS:]
    n_cols = 2 * len(names)
    columns: List[List[str]] = [[] for _ in range(n_cols)]
    for row in data_rows:
        for i in range(n_cols):
            columns[i].append(row[i] if i < len(row) else "")

    channels: Dict[str, Channel] = {}
    markers: List[Tuple[float, str]] = []
    for k, name in enumerate(names):
        volume = _to_float_array(columns[2 * k])
        text_col = columns[2 * k + 1]
        if name == "Run Log":
            markers.extend(_text_markers(volume, text_col, "Phase "))
            continue
        if name == "Fraction":
            markers.extend(_text_markers(volume, text_col, ""))
            continue

        values = _to_float_array(text_col)
        valid = ~(np.isnan(volume) | np.isnan(values))
        v, s = volume[valid], values[valid]
        order = np.argsort(v)
        channels[name] = Channel(name=name, x=v[order], values=s[order])

    if not channels:
        raise ValueError("No numeric channels found.")

    markers.sort(key=lambda m: m[0])
    return ExperimentalRun(
        label=label, channels=channels, x_basis="volume", x_unit="mL", markers=markers
    )


def read_experimental_csv(content: bytes, label: str) -> ExperimentalRun:
    """Auto-detect and parse an Äkta/Unicorn export or a generic header CSV."""
    if is_akta_format(content):
        return read_akta_csv(content, label)
    return read_generic_csv(content, label)


def _generic_headers(run: ExperimentalRun) -> Optional[List[str]]:
    """Header row for the generic format, or None if `run` can't round-trip through it."""
    if run.markers:
        return None
    channels = list(run.channels.values())
    x = channels[0].x
    if any(ch.x.shape != x.shape or not np.array_equal(ch.x, x) for ch in channels[1:]):
        return None
    x_header = "Volume (mL)" if run.x_basis == "volume" else "Time (s)"
    headers = [x_header, *run.channels]
    expected = ["volume_ml" if run.x_basis == "volume" else "time_s"] + ["signal"] * len(channels)
    if detect_column_roles(headers) != expected or any(not name.strip() for name in run.channels):
        return None
    return headers


def write_experimental_csv(run: ExperimentalRun) -> bytes:
    """Serialize `run` so `read_experimental_csv` reads back its channels, x basis and markers.

    Writes the generic one-header-row format when every channel shares one x axis and
    there are no markers; otherwise an Äkta-style export (volume axis only), with markers
    starting with `"Phase "` in a `Run Log` column and the rest in a `Fraction` column.
    """
    if not run.channels:
        raise ValueError("A run needs at least one channel.")
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    headers = _generic_headers(run)
    if headers is not None:
        channels = list(run.channels.values())
        writer.writerow(headers)
        for i, x in enumerate(channels[0].x):
            writer.writerow([repr(float(x)), *(repr(float(ch.values[i])) for ch in channels)])
        return out.getvalue().encode("utf-8")

    if run.x_basis != "volume":
        raise ValueError(
            "Only volume-axis runs can be written with markers or per-channel x axes."
        )
    reserved = {"Run Log", "Fraction"} & set(run.channels)
    if reserved:
        raise ValueError(f"Channel name(s) {sorted(reserved)} are reserved for markers.")
    phases = [(x, t) for x, t in run.markers if t.startswith("Phase ")]
    others = [(x, t) for x, t in run.markers if not t.startswith("Phase ")]
    columns: List[Tuple[str, str, List[Tuple[str, str]]]] = [
        (name, ch.unit or "", [(repr(float(x)), repr(float(v))) for x, v in zip(ch.x, ch.values)])
        for name, ch in run.channels.items()
    ]
    for name, markers in (("Run Log", phases), ("Fraction", others)):
        if markers:
            columns.append((name, "", [(repr(float(x)), t) for x, t in markers]))

    writer.writerow([run.label, ""] * len(columns))
    writer.writerow([cell for name, _, _ in columns for cell in (name, "")])
    writer.writerow([cell for _, unit, _ in columns for cell in (run.x_unit, unit)])
    n_rows = max(len(values) for _, _, values in columns)
    for i in range(n_rows):
        row: List[str] = []
        for _, _, values in columns:
            row.extend(values[i] if i < len(values) else ("", ""))
        writer.writerow(row)
    return out.getvalue().encode("utf-8")


def to_time(
    run: ExperimentalRun, channel: str, flow_rate: Optional[float] = None
) -> Tuple[np.ndarray, np.ndarray]:
    """Return `(time_s, values)`; volume axes need a constant `flow_rate` (m^3/s)."""
    ch = run.channels[channel]
    if run.x_basis == "time":
        return ch.x, ch.values
    if flow_rate is None:
        raise ValueError("flow_rate is required to convert a volume-basis run to time.")
    time_s = ch.x * 1e-6 / flow_rate
    return time_s, ch.values


def to_reference(
    run: ExperimentalRun, channel: str, flow_rate: Optional[float] = None
) -> ReferenceIO:
    """Build a `CADETProcess.reference.ReferenceIO` for one channel."""
    from CADETProcess.reference import ReferenceIO

    time_s, values = to_time(run, channel, flow_rate)
    return ReferenceIO(f"{run.label}: {channel}", time_s, values, flow_rate=flow_rate)
