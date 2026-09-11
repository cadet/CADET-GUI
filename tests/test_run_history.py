from __future__ import annotations

from cadetgui.widgets.composite import RunHistoryWidget


def test_record_appends_and_selects_newest():
    h = RunHistoryWidget()
    h.record("first", result="r1")
    h.record("second", result="r2")

    assert [r.label for r in h.runs] == ["first", "second"]
    assert h.selected.label == "second"
    assert h.selected.result == "r2"


def test_record_marks_ok_vs_error():
    h = RunHistoryWidget()
    ok_run = h.record("ok-run", result=42)
    bad_run = h.record("bad-run", error="boom")

    assert ok_run.ok is True
    assert bad_run.ok is False
    assert "boom" in bad_run.error


def test_picking_a_run_notifies_listeners():
    h = RunHistoryWidget()
    h.record("first", result="r1")
    h.record("second", result="r2")

    seen = []
    h.add_listener(seen.append)

    h._picker.selected_index = 0
    assert len(seen) == 1
    assert seen[0].label == "first"


def test_picking_the_same_run_again_does_not_renotify():
    h = RunHistoryWidget()
    h.record("only", result="r1")

    seen = []
    h.add_listener(seen.append)
    h._picker.selected_index = 0  # already selected; no real change
    assert seen == []


def test_clear_empties_history():
    h = RunHistoryWidget()
    h.record("first", result="r1")
    h.clear()

    assert h.runs == []
    assert h.selected is None
    assert h._picker.option_labels == []


def test_describe_format_includes_index_and_status():
    h = RunHistoryWidget()
    h.record("MyProcess", result="ok")
    label = h._picker.option_labels[0]
    assert label.startswith("#1")
    assert "MyProcess" in label
    assert label.endswith("ok")


def test_record_carries_config_name_and_hash():
    h = RunHistoryWidget()
    run = h.record("first", result="r1", config_name="My Config", config_hash="abc123")

    assert run.config_name == "My Config"
    assert run.config_hash == "abc123"


def test_record_without_config_leaves_hash_none():
    h = RunHistoryWidget()
    run = h.record("first", result="r1")

    assert run.config_name is None
    assert run.config_hash is None
