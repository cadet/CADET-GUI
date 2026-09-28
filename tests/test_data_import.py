from __future__ import annotations

import datetime as dt

from cadetgui.widgets.composite import DataImportWidget


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
