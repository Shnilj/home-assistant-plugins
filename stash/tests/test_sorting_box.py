"""Sorting box layout invariants, persistence, imports and HTTP."""
import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import model, store
from app.controller import Controller
from app.store import ValidationError
from app.web.server import create_app


def cell(col, row):
    return {"col": col, "row": row}


@pytest.fixture
def ctl(tmp_path):
    controller = Controller(str(tmp_path / "stash.json"), seed_path=None)
    controller.save_place({"name": "Wall", "kind": "grid", "cols": 4, "rows": 4})
    controller.save_place({"name": "Sortimo", "kind": "sorting_box", "parent": "wall",
                           "cell": cell(2, 3), "cols": 6, "rows": 4})
    return controller


def merge(ctl, first=(1, 1), last=(2, 2)):
    return ctl.merge_cells("sortimo", {"from": cell(*first), "to": cell(*last)})


def item(ctl, name="Screws", at=(2, 2), qty=3):
    return ctl.save_item({"name": name, "locations": [
        {"place": "sortimo", "cell": cell(*at), "qty": qty}]})


def test_creation_and_nested_path(ctl):
    view = ctl.place("sortimo")
    assert view["place"]["kind_label"] == "Sorting box"
    assert view["place"]["cols"] == 6
    assert view["grid"]["rows"] == 4
    assert [s["kind"] for s in view["path"]] == ["grid", "cell", "sorting_box"]


def test_merge_moves_contents_and_combines_counts_notes(ctl):
    made = item(ctl, at=(1, 1), qty=3)
    ctl.add_location(made["id"], {"place": "sortimo", "cell": cell(2, 2), "qty": 4, "note": "spare"})
    ctl.save_place({"name": "Small bin", "kind": "container", "parent": "sortimo", "cell": cell(2, 1)})
    view = merge(ctl)
    locs = ctl.item(made["id"])["locations"]
    assert len(locs) == 1
    assert locs[0]["qty"] == 7 and locs[0]["note"] == "spare"
    assert locs[0]["cell"] == cell(1, 1)
    assert ctl.place("small_bin")["place"]["cell"] == cell(1, 1)
    assert view["grid"]["cells"]["1,1"]["items"] == 1
    assert "Columns 1–2, rows 1–2" in locs[0]["text"]


@pytest.mark.parametrize("first_qty,second_qty", [(None, 2), (2, None)])
def test_merge_uncounted_stays_uncounted(ctl, first_qty, second_qty):
    made = item(ctl, at=(1, 1), qty=first_qty)
    ctl.add_location(made["id"], {"place": "sortimo", "cell": cell(2, 2), "qty": second_qty})
    merge(ctl)
    assert ctl.item(made["id"])["locations"][0]["qty"] is None


def test_all_cells_resolve_to_merged_anchor(ctl):
    merge(ctl)
    for col in (1, 2):
        for row in (1, 2):
            made = item(ctl, name="Part %s %s" % (col, row), at=(col, row))
            assert made["locations"][0]["cell"] == cell(1, 1)
            assert ctl.place("sortimo", cell(col, row))["cell"] == cell(1, 1)
    assert len(ctl.place("sortimo", cell(2, 2))["items"]) == 4


def test_partial_overlap_rejected_without_changes(ctl):
    merge(ctl)
    before = copy.deepcopy(ctl._data)
    with pytest.raises(ValidationError, match="whole"):
        merge(ctl, (2, 2), (3, 3))
    assert ctl._data == before
    assert store.read(ctl.path) == before


def test_merge_existing_rectangles_and_reverse_corners(ctl):
    merge(ctl)
    merge(ctl, (3, 1), (4, 2))
    merge(ctl, (4, 2), (1, 1))
    assert ctl.place("sortimo")["place"]["merged_cells"] == [
        {"col": 1, "row": 1, "cols": 4, "rows": 2}]


@pytest.mark.parametrize("first,last", [((1, 1), (1, 1)), ((0, 1), (2, 2)), ((1, 1), (7, 2))])
def test_bad_selections_do_not_mutate(ctl, first, last):
    before = copy.deepcopy(ctl._data)
    with pytest.raises(ValidationError):
        merge(ctl, first, last)
    assert ctl._data == before


def test_split_requires_valid_landing_for_contents(ctl):
    made = item(ctl)
    ctl.save_place({"name": "Bin", "kind": "container", "parent": "sortimo", "cell": cell(2, 2)})
    merge(ctl)
    before = copy.deepcopy(ctl._data)
    for payload in ({"cell": cell(2, 2)}, {"cell": cell(2, 2), "target": cell(3, 3)}):
        with pytest.raises(ValidationError):
            ctl.split_cell("sortimo", payload)
        assert ctl._data == before
    ctl.split_cell("sortimo", {"cell": cell(2, 2), "target": cell(2, 1)})
    assert ctl.item(made["id"])["locations"][0]["cell"] == cell(2, 1)
    assert ctl.place("bin")["place"]["cell"] == cell(2, 1)
    assert not ctl.place("sortimo")["place"]["merged_cells"]
    assert ctl.place("sortimo", cell(1, 1))["items"] == []


def test_empty_split_and_repeated_split(ctl):
    merge(ctl)
    ctl.split_cell("sortimo", {"cell": cell(2, 2)})
    with pytest.raises(ValidationError, match="single"):
        ctl.split_cell("sortimo", {"cell": cell(1, 1)})


@pytest.mark.parametrize("cols_from,rows_from", [("left", "top"), ("right", "top"), ("left", "bottom"), ("right", "bottom")])
def test_direction_changes_preserve_rectangles_and_contents(ctl, cols_from, rows_from):
    made = item(ctl)
    merge(ctl)
    ctl.save_place({"id": "sortimo", "count_cols_from": cols_from, "count_rows_from": rows_from})
    rect = ctl.place("sortimo")["place"]["merged_cells"][0]
    assert rect == {"col": 5 if cols_from == "right" else 1,
                    "row": 3 if rows_from == "bottom" else 1, "cols": 2, "rows": 2}
    assert ctl.item(made["id"])["locations"][0]["cell"] == cell(rect["col"], rect["row"])


def test_resize_and_kind_change_protect_layout_even_when_empty(ctl):
    merge(ctl, (5, 3), (6, 4))
    before = copy.deepcopy(ctl._data)
    for change in ({"cols": 5}, {"rows": 3}, {"kind": "container"},
                   {"merged_cells": []}):
        with pytest.raises(ValidationError):
            ctl.save_place(dict(change, id="sortimo"))
        assert ctl._data == before
    ctl.save_place({"id": "sortimo", "cols": 8, "rows": 5})
    assert ctl.place("sortimo")["place"]["merged_cells"][0]["col"] == 5


def test_save_reload_and_import_resolve_covered_cells(ctl):
    merge(ctl)
    report = ctl.import_batch({"spot": {"place": "sortimo", "cell": cell(2, 2)},
                               "items": [{"name": "Nuts", "qty": 8}]}, dry_run=False)
    assert report["counts"]["items_created"] == 1
    reopened = Controller(ctl.path, seed_path=None)
    assert reopened.item("nuts")["locations"][0]["cell"] == cell(1, 1)
    assert reopened.place("sortimo")["place"]["merged_cells"] == ctl.place("sortimo")["place"]["merged_cells"]


def test_hand_edit_canonicalizes_locations_and_children(ctl):
    data = copy.deepcopy(ctl._data)
    data["places"][1]["merged_cells"] = [{"col": 1, "row": 1, "cols": 2, "rows": 2}]
    data["places"].append({"name": "Bin", "kind": "container", "parent": "sortimo", "cell": cell(2, 2)})
    data["items"] = [{"name": "Parts", "locations": [
        {"place": "sortimo", "cell": cell(1, 1), "qty": 2},
        {"place": "sortimo", "cell": cell(2, 2), "qty": 3}]}]
    result = store.normalize_data(data)
    assert result["places"][-1]["cell"] == cell(1, 1)
    assert len(result["items"][0]["locations"]) == 1
    assert result["items"][0]["locations"][0]["qty"] == 5


@pytest.mark.parametrize("rects", [
    [{"col": 1, "row": 1, "cols": 7, "rows": 2}],
    [{"col": 1, "row": 1, "cols": 2, "rows": 2}, {"col": 2, "row": 2, "cols": 2, "rows": 2}],
    [{"col": 1, "row": 1, "cols": 1.5, "rows": 2}],
    [{"col": True, "row": 1, "cols": 2, "rows": 2}],
    "bad",
])
def test_invalid_rectangle_data_is_rejected(rects):
    with pytest.raises(ValidationError):
        store.normalize_place({"name": "Bad", "kind": "sorting_box", "cols": 6, "rows": 4,
                               "merged_cells": rects})


def test_delete_sorting_box_passes_contents_to_parent_cell(ctl):
    made = item(ctl)
    merge(ctl)
    ctl.delete_place("sortimo")
    loc = ctl.item(made["id"])["locations"][0]
    assert loc["place"] == "wall" and loc["cell"] == cell(2, 3)


def test_http_and_ingress_assets(ctl):
    client = create_app(ctl).test_client()
    assert client.post("/api/places/sortimo/merge", json={"from": cell(1, 1), "to": cell(2, 2)}).status_code == 200
    item(ctl)
    assert client.get("/api/places/sortimo?col=2&row=2").json["cell"] == cell(1, 1)
    assert client.post("/api/places/sortimo/split", json={"cell": cell(1, 1)}).status_code == 400
    assert client.post("/api/places/sortimo/split", json={"cell": cell(1, 1), "target": cell(2, 1)}).status_code == 200
    assert client.post("/api/places/wall/merge", json={"from": cell(1, 1), "to": cell(2, 2)}).status_code == 400
    assert client.post("/api/places/missing/merge", json={}).status_code == 404
    assert client.get("/static/app.js").status_code == 200
