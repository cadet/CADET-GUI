"""Experimental data: generic CSV, ÄKTA export, column roles, time axis, CSV round trips."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from cadetgui.io.experimental_data import (
    Channel,
    ExperimentalRun,
    detect_column_roles,
    is_akta_format,
    read_akta_csv,
    read_experimental_csv,
    read_generic_csv,
    read_headers,
    to_reference,
    to_time,
    write_experimental_csv,
)

EXAMPLE_AKTA = (
    Path(__file__).parents[2]
    / "examples"
    / "data"
    / "characterization_akta"
    / "system_pulse_1_uv.csv"
)


def akta_text(channels, text_channels) -> str:
    """A synthetic ÄKTA export: 3 header rows, one (volume, value) column pair per channel."""
    names = [*channels, *text_channels]
    pairs = [[(str(v), str(s)) for v, s in zip(*xy)] for xy in channels.values()]
    pairs += [[(str(v), t) for v, t in entries] for entries in text_channels.values()]
    rows = [
        [""] * (2 * len(names)),
        [cell for name in names for cell in (name, "")],
        [cell for _ in names for cell in ("mL", "AU")],
    ]
    for r in range(max(len(p) for p in pairs)):
        rows.append([cell for p in pairs for cell in (p[r] if r < len(p) else ("", ""))])
    return "\n".join(",".join(row) for row in rows)


def _run(x_basis, channels, markers=()):
    return ExperimentalRun(
        label="r",
        channels={
            name: Channel(name, np.asarray(x, float), np.asarray(y, float))
            for name, (x, y) in channels.items()
        },
        x_basis=x_basis,
        x_unit="mL" if x_basis == "volume" else "s",
        markers=list(markers),
    )


@pytest.mark.parametrize(
    "headers, roles",
    [
        (["Time [s]", "Volume [mL]", "Absorbance [mAU]"], ["signal", "volume_ml", "signal"]),
        (["time", "signal"], ["time_s", "signal"]),
        (["Time [min]", "signal"], ["time_min", "signal"]),
        (["A", "B", "C"], ["time_s", "signal", "signal"]),
    ],
)
def test_detect_column_roles(headers, roles):
    assert detect_column_roles(headers) == roles


@pytest.mark.parametrize(
    "content, basis, x, channels",
    [
        (
            b"Time [s],Conductivity [mS/cm],Absorbance [mAU]\n0,1.9,0\n10,1.9,5\n20,1.9,10\n",
            "time",
            [0, 10, 20],
            ["Conductivity [mS/cm]", "Absorbance [mAU]"],
        ),
        (b"Volume [mL],UV\n0,0\n5,1\n10,2\n", "volume", [0, 5, 10], ["UV"]),
        (b"Time [min],signal\n0,0\n1,1\n2,2\n", "time", [0, 60, 120], ["signal"]),
        (b"time,signal\n0,0\nnot,a,number\n2,1\n", "time", [0, 2], ["signal"]),
        (b"time_s\tsignal\n0\t0.1\n1\t0.2\n", "time", [0, 1], ["signal"]),
        (
            "Instrument: LC-1\nOperator: someone\n\nTime (min);UV (mAU);Cond (mS/cm)\n"
            "0,0;1,5;40,0\n0,5;2,5;40,1\n".encode(),
            "time",
            [0, 30],
            ["UV (mAU)", "Cond (mS/cm)"],
        ),
    ],
    ids=["two signals", "volume", "minutes", "bad row", "tabs", "semicolon decimal comma"],
)
def test_generic_csv_detects_the_x_axis_and_signal_channels(content, basis, x, channels):
    assert not is_akta_format(content)
    assert read_headers(content)[-len(channels) :] == channels

    run = read_experimental_csv(content, "run1")

    assert run.x_basis == basis
    assert list(run.channels) == channels
    np.testing.assert_allclose(run.channels[channels[0]].x, x)


def test_generic_csv_roles_can_skip_columns_and_need_exactly_one_x_axis():
    content = b"time,notes,signal\n0,foo,1\n1,bar,2\n"
    run = read_generic_csv(content, "run1", roles=["time_s", "skip", "signal"])
    assert list(run.channels) == ["signal"]
    for roles in (["signal", "signal", "signal"], ["time_s", "volume_ml", "signal"]):
        with pytest.raises(ValueError):
            read_generic_csv(content, "run1", roles=roles)
    assert read_headers(b"") == []


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "latin-1"])
def test_akta_export_reads_channels_at_their_own_rates_and_run_log_markers(encoding):
    text = akta_text(
        {
            "UV_1_280": ([0.0, 5.0, 10.0, 15.0], [0.0, 1.0, 2.0, 1.0]),
            "Cond [µS/cm]": ([0.0, 7.5], [1.5, 1.6]),
        },
        {
            "Run Log": [(3.0, "Phase Equilibration"), (8.0, "Phase Elution"), (12.0, "Note: pH")],
            "Fraction": [(0.5, "A1")],
        },
    )
    content = text.encode(encoding)
    assert is_akta_format(content)

    run = read_experimental_csv(content, "run1")

    assert (run.x_basis, run.x_unit) == ("volume", "mL")
    assert list(run.channels) == ["UV_1_280", "Cond [µS/cm]"]
    assert run.channels["UV_1_280"].values.tolist() == [0.0, 1.0, 2.0, 1.0]
    assert run.channels["Cond [µS/cm]"].x.tolist() == [0.0, 7.5]
    assert sorted(run.markers) == [
        (0.5, "A1"),
        (3.0, "Phase Equilibration"),
        (8.0, "Phase Elution"),
    ]


def test_akta_reader_rejects_a_generic_csv():
    with pytest.raises(ValueError):
        read_akta_csv(b"Time [s],Absorbance [mAU]\n0,0\n1,1\n", "run1")


def test_volume_axis_converts_to_time_with_the_flow_rate():
    volume_run = _run("volume", {"signal": (np.linspace(0.0, 50.0, 6), np.arange(6.0))})
    with pytest.raises(ValueError):
        to_time(volume_run, "signal")

    time_s, values = to_time(volume_run, "signal", 1e-8)
    assert time_s.tolist() == pytest.approx(np.linspace(0.0, 5000.0, 6).tolist())
    assert values.tolist() == list(range(6))
    assert to_time(_run("time", {"signal": ([0, 1], [2, 3])}), "signal")[0].tolist() == [0, 1]

    reference = to_reference(volume_run, "signal", flow_rate=1e-8)
    assert reference.name == "r: signal"
    assert reference.time.tolist() == pytest.approx(time_s.tolist())


@pytest.mark.parametrize(
    "run, akta",
    [
        (
            _run(
                "time",
                {
                    "UV": (np.arange(5) / 3, np.sin(np.arange(5))),
                    "Cond": (np.arange(5) / 3, np.ones(5)),
                },
            ),
            False,
        ),
        (_run("volume", {"UV 1_280": ([0.0, 0.5, 1.0], [0.0, 1.0, 2.0])}), False),
        (
            _run(
                "volume",
                {
                    "UV 1_280": ([0.0, 0.1, 0.2], [1.0, 2.0, 3.0]),
                    "Cond": ([0.0, 0.25], [40.0, 41.0]),
                },
                markers=[(0.0, "Phase Equilibration"), (0.1, "A1"), (0.2, "Phase Elution")],
            ),
            True,
        ),
        (read_experimental_csv(EXAMPLE_AKTA.read_bytes(), "r"), True),
    ],
    ids=["generic time", "generic volume", "akta with markers", "example export"],
)
def test_written_csv_reads_back_to_the_same_run(run, akta):
    content = write_experimental_csv(run)
    assert is_akta_format(content) == akta

    read = read_experimental_csv(content, "r")

    assert list(read.channels) == list(run.channels)
    assert (read.x_basis, read.x_unit, read.markers) == (run.x_basis, run.x_unit, run.markers)
    for name, channel in run.channels.items():
        np.testing.assert_array_equal(read.channels[name].x, channel.x)
        np.testing.assert_array_equal(read.channels[name].values, channel.values)


def test_time_axis_with_markers_cannot_be_written():
    run = _run("time", {"UV": ([0.0, 1.0], [0.0, 1.0])}, markers=[(0.0, "Phase Elution")])
    with pytest.raises(ValueError, match="volume-axis"):
        write_experimental_csv(run)
