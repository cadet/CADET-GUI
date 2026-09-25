from __future__ import annotations

from dataclasses import dataclass

import pytest
from cadetgui._record_store import list_records, load_record, save_record


@dataclass
class _Thing:
    id: str
    value: int


def test_save_and_load_round_trip(tmp_path):
    save_record("thing", "abc", _Thing(id="abc", value=42), tmp_path)

    loaded = load_record("thing", "abc", _Thing, tmp_path)

    assert loaded == _Thing(id="abc", value=42)


def test_load_missing_record_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_record("thing", "missing", _Thing, tmp_path)


def test_list_records_is_newest_first_and_skips_unreadable(tmp_path):
    save_record("thing", "a", _Thing(id="a", value=1), tmp_path)
    save_record("thing", "b", _Thing(id="b", value=2), tmp_path)
    (tmp_path / "thing_broken.json").write_text("not json")

    records = list_records("thing", _Thing, tmp_path)

    assert [r.id for r in records] == ["b", "a"]


def test_different_prefixes_do_not_collide(tmp_path):
    save_record("thing", "x", _Thing(id="x", value=1), tmp_path)
    save_record("other", "x", _Thing(id="x", value=2), tmp_path)

    assert [r.value for r in list_records("thing", _Thing, tmp_path)] == [1]
    assert [r.value for r in list_records("other", _Thing, tmp_path)] == [2]
