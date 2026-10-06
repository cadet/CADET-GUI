from __future__ import annotations

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


def _akta_text(
    channels: dict[str, tuple[list[float], list[float]]],
    text_channels: dict[str, list[tuple[float, str]]],
) -> str:
    """A synthetic Äkta/Unicorn-style export: 3 header rows, one column pair per channel.

    Each channel (numeric or text) is sampled independently, so pairs may have
    different lengths; short columns are padded with empty cells.
    """
    names = list(channels) + list(text_channels)
    block_row = [""] * (2 * len(names))
    name_row = [cell for name in names for cell in (name, "")]
    unit_row = [cell for name in names for cell in ("mL", "AU")]

    pairs: list[list[tuple[str, str]]] = []
    for vol, val in channels.values():
        pairs.append([(str(v), str(s)) for v, s in zip(vol, val)])
    for entries in text_channels.values():
        pairs.append([(str(v), t) for v, t in entries])

    n_rows = max((len(p) for p in pairs), default=0)
    data_rows = []
    for r in range(n_rows):
        row: list[str] = []
        for p in pairs:
            row.extend(p[r] if r < len(p) else ("", ""))
        data_rows.append(row)

    rows = [block_row, name_row, unit_row, *data_rows]
    return "\n".join(",".join(row) for row in rows)


class TestDetectColumnRoles:
    def test_prefers_volume_over_time(self):
        roles = detect_column_roles(["Time [s]", "Volume [mL]", "Absorbance [mAU]"])
        assert roles == ["signal", "volume_ml", "signal"]

    def test_falls_back_to_time_seconds(self):
        assert detect_column_roles(["time", "signal"]) == ["time_s", "signal"]

    def test_detects_time_minutes(self):
        assert detect_column_roles(["Time [min]", "signal"]) == ["time_min", "signal"]

    def test_falls_back_to_first_column_with_no_recognizable_header(self):
        assert detect_column_roles(["A", "B", "C"]) == ["time_s", "signal", "signal"]


class TestGenericCsv:
    def test_auto_detects_time_and_two_signal_channels(self):
        content = (
            b"Time [s],Conductivity [mS/cm],Absorbance [mAU]\n"
            b"0,1.9,0\n10,1.9,5\n20,1.9,10\n"
        )
        run = read_generic_csv(content, "run1")
        assert run.x_basis == "time"
        assert run.x_unit == "s"
        assert set(run.channels) == {"Conductivity [mS/cm]", "Absorbance [mAU]"}
        assert run.channels["Absorbance [mAU]"].values.tolist() == [0.0, 5.0, 10.0]
        assert run.channels["Absorbance [mAU]"].x.tolist() == [0.0, 10.0, 20.0]

    def test_volume_basis_column(self):
        content = b"Volume [mL],Absorbance [mAU]\n0,0\n5,1\n10,2\n"
        run = read_generic_csv(content, "run1")
        assert run.x_basis == "volume"
        assert run.x_unit == "mL"

    def test_time_minutes_normalized_to_seconds(self):
        content = b"Time [min],signal\n0,0\n1,1\n2,2\n"
        run = read_generic_csv(content, "run1")
        channel = next(iter(run.channels.values()))
        assert run.x_basis == "time"
        assert channel.x.tolist() == [0.0, 60.0, 120.0]

    def test_explicit_roles_skip_a_column(self):
        content = b"time,notes,signal\n0,foo,1\n1,bar,2\n"
        run = read_generic_csv(content, "run1", roles=["time_s", "skip", "signal"])
        assert set(run.channels) == {"signal"}

    def test_requires_exactly_one_x_column(self):
        content = b"a,b\n0,1\n2,3\n"
        with pytest.raises(ValueError):
            read_generic_csv(content, "run1", roles=["signal", "signal"])
        with pytest.raises(ValueError):
            read_generic_csv(content, "run1", roles=["time_s", "volume_ml"])

    def test_skips_unparseable_rows(self):
        content = b"time,signal\n0,0\nnot,a,number\n2,1\n"
        run = read_generic_csv(content, "run1")
        channel = next(iter(run.channels.values()))
        assert channel.x.tolist() == [0.0, 2.0]

    def test_read_headers(self):
        assert read_headers(b"a,b,c\n1,2,3\n") == ["a", "b", "c"]
        assert read_headers(b"") == []


class TestAktaCsv:
    def test_is_akta_format_detects_export(self):
        text = _akta_text({"UV": ([0.0, 1.0], [0.0, 1.0])}, {"Run Log": []})
        assert is_akta_format(text.encode("utf-8"))

    def test_is_akta_format_rejects_generic_csv(self):
        content = b"Time [s],Absorbance [mAU]\n0,0\n1,1\n"
        assert not is_akta_format(content)

    def test_two_channels_sampled_at_different_rates_and_run_log_markers(self):
        text = _akta_text(
            channels={
                "UV_1_280": ([0.0, 5.0, 10.0, 15.0], [0.0, 1.0, 2.0, 1.0]),
                "Cond": ([0.0, 7.5, 15.0], [1.5, 1.5, 1.5]),
            },
            text_channels={
                "Run Log": [
                    (3.0, "Phase Equilibration"),
                    (8.0, "Phase Elution"),
                    (12.0, "Note: pH check"),
                ]
            },
        )
        run = read_akta_csv(text.encode("utf-8"), "run1")

        assert run.x_basis == "volume"
        assert run.x_unit == "mL"
        assert set(run.channels) == {"UV_1_280", "Cond"}
        assert run.channels["UV_1_280"].x.tolist() == [0.0, 5.0, 10.0, 15.0]
        assert run.channels["UV_1_280"].values.tolist() == [0.0, 1.0, 2.0, 1.0]
        assert run.channels["Cond"].x.tolist() == [0.0, 7.5, 15.0]
        # "Note: pH check" does not start with "Phase " and is dropped.
        assert run.markers == [(3.0, "Phase Equilibration"), (8.0, "Phase Elution")]

    def test_fraction_channel_becomes_markers_not_a_channel(self):
        text = _akta_text(
            channels={"UV": ([0.0, 1.0, 2.0], [0.0, 1.0, 0.0])},
            text_channels={"Fraction": [(0.5, "A1"), (1.5, "A2")]},
        )
        run = read_akta_csv(text.encode("utf-8"), "run1")

        assert "Fraction" not in run.channels
        assert run.markers == [(0.5, "A1"), (1.5, "A2")]

    def test_rejects_generic_csv(self):
        with pytest.raises(ValueError):
            read_akta_csv(b"Time [s],Absorbance [mAU]\n0,0\n1,1\n", "run1")

    def test_handles_utf16_encoding(self):
        text = _akta_text(
            {"UV": ([0.0, 1.0, 2.0, 3.0], [0.0, 2.0, 4.0, 2.0])},
            {"Run Log": [(0.5, "Phase Elution")]},
        )
        run = read_akta_csv(text.encode("utf-16"), "run1")
        assert run.channels["UV"].values.tolist() == [0.0, 2.0, 4.0, 2.0]
        assert run.markers == [(0.5, "Phase Elution")]

    def test_handles_latin1_encoding(self):
        text = _akta_text({"Cond [µS/cm]": ([0.0, 1.0], [1.5, 1.6])}, {"Run Log": []})
        run = read_akta_csv(text.encode("latin-1"), "run1")
        assert "Cond [µS/cm]" in run.channels


class TestReadExperimentalCsv:
    def test_dispatches_to_akta_reader(self):
        text = _akta_text({"UV": ([0.0, 1.0], [0.0, 1.0])}, {"Run Log": []})
        run = read_experimental_csv(text.encode("utf-8"), "run1")
        assert run.x_basis == "volume"

    def test_dispatches_to_generic_reader(self):
        run = read_experimental_csv(b"time,signal\n0,0\n1,1\n", "run1")
        assert run.x_basis == "time"


class TestToTime:
    def test_time_basis_passes_through(self):
        channel = Channel(
            name="signal", x=np.array([0.0, 1.0, 2.0]), values=np.array([0.0, 1.0, 0.5])
        )
        run = ExperimentalRun(
            label="r", channels={"signal": channel}, x_basis="time", x_unit="s"
        )
        time_s, values = to_time(run, "signal")
        assert time_s.tolist() == [0.0, 1.0, 2.0]
        assert values.tolist() == [0.0, 1.0, 0.5]

    def test_volume_basis_requires_flow_rate(self):
        channel = Channel(name="signal", x=np.array([0.0, 10.0]), values=np.array([0.0, 1.0]))
        run = ExperimentalRun(
            label="r", channels={"signal": channel}, x_basis="volume", x_unit="mL"
        )
        with pytest.raises(ValueError):
            to_time(run, "signal")

    def test_volume_to_time_conversion(self):
        channel = Channel(
            name="signal", x=np.array([0.0, 10.0, 20.0]), values=np.array([0.0, 1.0, 2.0])
        )
        run = ExperimentalRun(
            label="r", channels={"signal": channel}, x_basis="volume", x_unit="mL"
        )
        flow_rate = 1e-8  # m^3/s
        time_s, values = to_time(run, "signal", flow_rate)
        # time_s = volume_mL * 1e-6 / flow_rate
        assert time_s.tolist() == pytest.approx([0.0, 1000.0, 2000.0])
        assert values.tolist() == [0.0, 1.0, 2.0]


class TestToReference:
    def test_builds_reference_io(self):
        x = np.linspace(0.0, 50.0, 6)
        values = np.linspace(0.0, 1.0, 6)
        channel = Channel(name="signal", x=x, values=values)
        run = ExperimentalRun(
            label="run1", channels={"signal": channel}, x_basis="volume", x_unit="mL"
        )

        reference = to_reference(run, "signal", flow_rate=1e-8)

        assert reference.name == "run1: signal"
        assert reference.time.tolist() == pytest.approx((x * 1e-6 / 1e-8).tolist())


def _assert_same_run(read: ExperimentalRun, run: ExperimentalRun) -> None:
    assert list(read.channels) == list(run.channels)
    assert (read.x_basis, read.x_unit) == (run.x_basis, run.x_unit)
    assert read.markers == run.markers
    for name, channel in run.channels.items():
        np.testing.assert_array_equal(read.channels[name].x, channel.x)
        np.testing.assert_array_equal(read.channels[name].values, channel.values)


class TestWriteExperimentalCsv:
    def test_shared_axis_without_markers_round_trips_as_generic_csv(self):
        x = np.linspace(0.0, 10.0, 11) / 3.0
        run = ExperimentalRun(
            label="r",
            channels={
                "UV": Channel("UV", x, np.sin(x)),
                "Cond": Channel("Cond", x, np.cos(x)),
            },
            x_basis="time", x_unit="s",
        )
        content = write_experimental_csv(run)
        assert not is_akta_format(content)
        _assert_same_run(read_experimental_csv(content, "r"), run)

    def test_volume_axis_generic_round_trip(self):
        x = np.array([0.0, 0.5, 1.0])
        run = ExperimentalRun(
            label="r", channels={"UV 1_280": Channel("UV 1_280", x, x * 2)},
            x_basis="volume", x_unit="mL",
        )
        _assert_same_run(read_experimental_csv(write_experimental_csv(run), "r"), run)

    def test_markers_and_per_channel_axes_round_trip_as_akta_export(self):
        run = ExperimentalRun(
            label="r",
            channels={
                "UV 1_280": Channel("UV 1_280", np.array([0.0, 0.1, 0.2, 0.3]),
                                    np.array([1.0, 2.0, 3.0, 4.0]), unit="mAU"),
                "Cond": Channel("Cond", np.array([0.0, 0.25]), np.array([40.0, 41.0])),
            },
            x_basis="volume", x_unit="mL",
            markers=[(0.0, "Phase Equilibration"), (0.1, "A1"), (0.2, "Phase Elution")],
        )
        content = write_experimental_csv(run)
        assert is_akta_format(content)
        _assert_same_run(read_experimental_csv(content, "r"), run)

    def test_the_example_akta_export_round_trips(self):
        from pathlib import Path

        path = (
            Path(__file__).parent.parent / "examples" / "data" / "characterization_akta"
            / "system_pulse_1_uv.csv"
        )
        run = read_experimental_csv(path.read_bytes(), "System pulse 1 (UV)")
        _assert_same_run(
            read_experimental_csv(write_experimental_csv(run), "System pulse 1 (UV)"), run,
        )

    def test_time_axis_with_markers_is_rejected(self):
        x = np.array([0.0, 1.0])
        run = ExperimentalRun(
            label="r", channels={"UV": Channel("UV", x, x)}, x_basis="time", x_unit="s",
            markers=[(0.0, "Phase Elution")],
        )
        with pytest.raises(ValueError, match="volume-axis"):
            write_experimental_csv(run)


def test_semicolon_decimal_comma_and_metadata_lines_are_read():
    content = (
        "Instrument: LC-1\nOperator: someone\n\n"
        "Time (min);UV (mAU);Cond (mS/cm)\n"
        "0,0;1,5;40,0\n0,5;2,5;40,1\n1,0;3,0;40,2\n"
    ).encode("utf-8")
    assert not is_akta_format(content)
    assert read_headers(content) == ["Time (min)", "UV (mAU)", "Cond (mS/cm)"]
    run = read_experimental_csv(content, "run")
    assert list(run.channels) == ["UV (mAU)", "Cond (mS/cm)"]
    np.testing.assert_allclose(run.channels["UV (mAU)"].values, [1.5, 2.5, 3.0])
    np.testing.assert_allclose(run.channels["UV (mAU)"].x, [0.0, 30.0, 60.0])


def test_tab_separated_export_is_read():
    content = b"time_s\tsignal\n0\t0.1\n1\t0.2\n2\t0.4\n"
    run = read_experimental_csv(content, "run")
    np.testing.assert_allclose(run.channels["signal"].values, [0.1, 0.2, 0.4])
