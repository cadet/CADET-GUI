from __future__ import annotations

import datetime as dt

import ipywidgets as W
import pytest
from cadetgui.widgets.composite import DataImportWidget

_MULTI_CHANNEL_CSV = (
    "Time [s],Conductivity [mS/cm],Absorbance [mAU]\n0,1.9,0\n10,1.9,5\n20,1.9,10\n"
)

# 3 header rows (block ids, channel names, units); UV_1_280 is a numeric channel, Run
# Log a text channel whose "Phase " entries become markers. UV_1_280 is sampled every
# row; Run Log only has one entry, the rest of its column is blank.
_AKTA_CSV = (
    "BLOCK1,,BLOCK2,\n"
    "UV_1_280,,Run Log,\n"
    "mL,AU,mL,\n"
    "0,0.0,1.0,Phase Elution\n"
    "5,1.0,,\n"
    "10,2.0,,\n"
    "15,1.0,,\n"
)


def _upload(widget: DataImportWidget, filename: str, csv_text: str) -> None:
    content = memoryview(csv_text.encode("utf-8"))
    widget._upload.value = (
        {
            "name": filename,
            "type": "text/csv",
            "size": len(content),
            "last_modified": dt.datetime.now(),
            "content": content,
        },
    )


def test_upload_parses_minutes_by_default():
    di = DataImportWidget()
    _upload(di, "run1.csv", "time,signal\n0,0.0\n1,0.5\n2,1.0\n")

    assert len(di.datasets) == 1
    ds = di.datasets[0]
    assert ds.label == "run1"
    assert ds.time_min.tolist() == [0.0, 1.0, 2.0]
    assert ds.signal.tolist() == [0.0, 0.5, 1.0]


def test_upload_converts_seconds_to_minutes():
    di = DataImportWidget()
    di._time_unit.value = "s"
    _upload(di, "run1.csv", "time,signal\n0,0.0\n60,1.0\n120,0.5\n")

    assert di.datasets[0].time_min.tolist() == [0.0, 1.0, 2.0]


def test_upload_skips_unparseable_rows_without_crashing():
    di = DataImportWidget()
    _upload(di, "messy.csv", "time,signal\n0,0.0\nnot,a,number\n2,1.0\n")

    assert di.datasets[0].time_min.tolist() == [0.0, 2.0]


def test_upload_of_unparseable_file_reports_error_and_adds_nothing():
    di = DataImportWidget()
    _upload(di, "empty.csv", "time,signal\n")

    assert di.datasets == []
    assert "Could not parse" in di.status.value


def test_multiple_uploads_accumulate_and_select_newest():
    di = DataImportWidget()
    _upload(di, "a.csv", "time,signal\n0,1\n")
    _upload(di, "b.csv", "time,signal\n0,2\n")

    assert [d.label for d in di.datasets] == ["a", "b"]
    assert di._dataset_picker.value.label == "b"


def test_remove_deletes_the_selected_dataset():
    di = DataImportWidget()
    _upload(di, "a.csv", "time,signal\n0,1\n")
    _upload(di, "b.csv", "time,signal\n0,2\n")

    di._dataset_picker.selected_index = 0  # "a"
    di._on_remove(None)

    assert [d.label for d in di.datasets] == ["b"]


def test_listener_fires_on_upload_and_remove():
    di = DataImportWidget()
    events = []
    di.add_listener(lambda: events.append(len(di.datasets)))

    _upload(di, "a.csv", "time,signal\n0,1\n")
    assert events == [1]

    di._on_remove(None)
    assert events == [1, 0]


def _panel_dropdowns(panel: W.VBox) -> list[W.Dropdown]:
    return [c for c in panel.children if isinstance(c, W.Dropdown)]


def _panel_flow_rate_field(panel: W.VBox) -> W.FloatText:
    return panel.children[-2].children[0]


def _panel_import_button(panel: W.VBox) -> W.Button:
    return panel.children[-1].children[0]


def test_multi_column_csv_queues_a_mapping_panel_with_prefilled_roles():
    di = DataImportWidget()
    _upload(di, "run1.csv", _MULTI_CHANNEL_CSV)

    assert di.datasets == []
    assert len(di._mapping_box.children) == 1
    roles = [d.value for d in _panel_dropdowns(di._mapping_box.children[0])]
    assert roles == ["time_s", "signal", "signal"]


def test_multi_column_csv_import_creates_one_dataset_per_signal_channel():
    di = DataImportWidget()
    _upload(di, "run1.csv", _MULTI_CHANNEL_CSV)
    panel = di._mapping_box.children[0]

    _panel_import_button(panel).click()

    assert {ds.channel for ds in di.datasets} == {"Conductivity [mS/cm]", "Absorbance [mAU]"}
    assert {ds.label for ds in di.datasets} == {
        "run1 — Conductivity [mS/cm]",
        "run1 — Absorbance [mAU]",
    }
    assert di._mapping_box.children == ()
    ds = next(d for d in di.datasets if d.channel == "Absorbance [mAU]")
    assert ds.time_min.tolist() == pytest.approx([0.0, 10 / 60, 20 / 60])
    assert ds.signal.tolist() == [0.0, 5.0, 10.0]
    assert ds.run.x_basis == "time"


def test_multi_column_csv_dropdown_can_skip_a_column():
    di = DataImportWidget()
    _upload(di, "run1.csv", _MULTI_CHANNEL_CSV)
    panel = di._mapping_box.children[0]
    _panel_dropdowns(panel)[1].value = "skip"  # Conductivity

    _panel_import_button(panel).click()

    assert [ds.channel for ds in di.datasets] == ["Absorbance [mAU]"]


def test_akta_export_is_auto_detected_and_queues_a_flow_rate_panel():
    di = DataImportWidget()
    _upload(di, "run1.csv", _AKTA_CSV)

    assert di.datasets == []
    assert len(di._mapping_box.children) == 1
    # Äkta channels/markers are auto-detected; no per-column dropdowns needed.
    assert _panel_dropdowns(di._mapping_box.children[0]) == []


def test_akta_export_import_converts_volume_to_time_via_flow_rate():
    di = DataImportWidget()
    _upload(di, "run1.csv", _AKTA_CSV)
    panel = di._mapping_box.children[0]
    _panel_flow_rate_field(panel).value = 60.0  # mL/min, i.e. 1 mL/s

    _panel_import_button(panel).click()

    assert len(di.datasets) == 1
    ds = di.datasets[0]
    assert ds.label == "run1"
    assert ds.channel == "UV_1_280"
    assert ds.time_min.tolist() == pytest.approx([0.0, 5 / 60, 10 / 60, 15 / 60])
    assert ds.signal.tolist() == [0.0, 1.0, 2.0, 1.0]
    assert ds.run.x_basis == "volume"
    assert ds.run.markers == [(1.0, "Phase Elution")]


def test_mapping_panel_cancel_discards_the_pending_file():
    di = DataImportWidget()
    _upload(di, "run1.csv", _MULTI_CHANNEL_CSV)
    panel = di._mapping_box.children[0]
    cancel_btn = panel.children[-1].children[1]

    cancel_btn.click()

    assert di.datasets == []
    assert di._mapping_box.children == ()
