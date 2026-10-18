"""Stash: model, store, controller and HTTP — temp files, no Supervisor."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import model, store  # noqa: E402
from app.controller import Controller, ItemNotFound  # noqa: E402
from app.store import ValidationError  # noqa: E402
from app.web.server import create_app  # noqa: E402

SEED = {
    "places": [
        {"id": "cave", "name": "Man cave", "kind": "room"},
        {"id": "left", "name": "Left Kallax", "kind": "grid", "parent": "cave",
         "cols": 16, "rows": 4, "count_cols_from": "right"},
        {"id": "right", "name": "Right Kallax", "kind": "grid", "parent": "cave",
         "cols": 8, "rows": 2},
        {"id": "box", "name": "Black box with lid", "kind": "container",
         "parent": "left", "cell": {"col": 14, "row": 2}},
        {"id": "behind", "name": "Behind the left Kallax", "kind": "area", "parent": "cave"},
    ],
    "items": [
        {"id": "usbc", "name": "USB-C cable", "category": "Cables", "tags": ["usb"],
         "locations": [
             {"id": "l1", "place": "box", "qty": 3},
             {"id": "l2", "place": "right", "cell": {"col": 3, "row": 1}, "qty": 2},
         ]},
        {"id": "hdmi", "name": "HDMI cable", "category": "Cables",
         "locations": [{"id": "l3", "place": "left", "cell": [14, 2], "qty": None}]},
        {"id": "xmas", "name": "Christmas lights", "category": "Decoration",
         "notes": "Kerstverlichting", "locations": [{"id": "l4", "place": "behind"}]},
    ],
}


@pytest.fixture()
def ctl(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(SEED), encoding="utf-8")
    return Controller(path=str(tmp_path / "stash.json"), seed_path=str(seed))


@pytest.fixture()
def client(ctl):
    return create_app(ctl).test_client()


def by_id(ctl):
    return model.index(ctl.places)


# ---------------------------------------------------------------- model


def test_ordinals():
    assert [model.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 14, 21, 22, 101, 111)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "14th", "21st", "22nd",
        "101st", "111th"]


def test_path_reads_like_walking_to_it(ctl):
    segments = model.path(by_id(ctl), "box")
    assert model.path_text(segments) == (
        "Man cave › Left Kallax › 14th from the right, 2nd from the top › Black box with lid")
    assert [s["kind"] for s in segments] == ["room", "grid", "cell", "container"]


def test_path_with_cell_on_location(ctl):
    text = model.path_text(model.path(by_id(ctl), "right", {"col": 3, "row": 1}))
    assert text == "Man cave › Right Kallax › 3rd from the left, 1st from the top"


def test_missing_place_is_visible_not_dropped():
    segments = model.path({}, "ghost")
    assert segments[0]["kind"] == "missing"


def test_physical_round_trip():
    grid = {"cols": 16, "rows": 4, "count_cols_from": "right", "count_rows_from": "bottom"}
    # 14th from the right on a 16-wide wall is the 3rd from the left.
    assert model.physical(grid, {"col": 14, "row": 2}) == (3, 3)
    assert model.from_physical(grid, 3, 3) == {"col": 14, "row": 2}


def test_renumber_keeps_physical_spot():
    old = {"cols": 16, "rows": 4, "count_cols_from": "right", "count_rows_from": "top"}
    new = dict(old, count_cols_from="left")
    cell = model.renumber(old, new, {"col": 14, "row": 2})
    assert cell == {"col": 3, "row": 2}
    assert model.physical(old, {"col": 14, "row": 2}) == model.physical(new, cell)


def test_grid_map_counts_box_contents(ctl):
    cells = model.grid_map(ctl.places, ctl.items, by_id(ctl)["left"])
    entry = cells["14,2"]
    # the HDMI cable directly in the compartment + the USB-C cable in the box
    assert entry["items"] == 2
    assert entry["containers"][0]["name"] == "Black box with lid"


@pytest.mark.parametrize("query", ["usb-c", "usbc", "USB C", "cable usb", "Usb"])
def test_search_forgives_punctuation_and_case(ctl, query):
    names = [i["name"] for i in model.search(ctl.places, ctl.items, query)["items"]]
    assert "USB-C cable" in names


def test_search_ranks_name_start_first(ctl):
    names = [i["name"] for i in model.search(ctl.places, ctl.items, "cable")["items"]]
    assert set(names) == {"USB-C cable", "HDMI cable"}
    names = [i["name"] for i in model.search(ctl.places, ctl.items, "hdmi")["items"]]
    assert names == ["HDMI cable"]


def test_search_hits_notes_and_accents(ctl):
    assert [i["id"] for i in model.search(ctl.places, ctl.items, "kerst")["items"]] == ["xmas"]
    ctl.save_item({"name": "Câble Ethernet"})
    assert model.search(ctl.places, ctl.items, "cable ethernet")["items"]


def test_search_finds_places(ctl):
    found = model.search(ctl.places, ctl.items, "black box")
    assert [p["id"] for p in found["places"]] == ["box"]


# ---------------------------------------------------------------- store


def test_parse_cell_shapes():
    assert store.parse_cell("14,2") == {"col": 14, "row": 2}
    assert store.parse_cell([14, 2]) == {"col": 14, "row": 2}
    assert store.parse_cell(None) is None
    with pytest.raises(ValidationError):
        store.parse_cell("0,2")


def test_loops_are_broken_on_read():
    data = store.normalize_data({"places": [
        {"id": "a", "name": "A", "parent": "b"},
        {"id": "b", "name": "B", "parent": "a"},
    ]})
    assert any(p["parent"] is None for p in data["places"])


def test_lenient_read_keeps_unknown_place(tmp_path):
    path = tmp_path / "stash.json"
    path.write_text(json.dumps({"items": [
        {"name": "Drill", "locations": [{"place": "typo_place"}]}]}))
    data = store.read(str(path))
    assert data["items"][0]["locations"][0]["place"] == "typo_place"


# ---------------------------------------------------------------- controller


def test_one_item_many_places(ctl):
    view = ctl.item("usbc")
    assert len(view["locations"]) == 2
    assert view["total"] == 5


def test_add_location_validates_cell(ctl):
    with pytest.raises(ValidationError):
        ctl.add_location("usbc", {"place": "right", "cell": {"col": 9, "row": 1}})
    with pytest.raises(ValidationError):
        ctl.add_location("usbc", {"place": "box", "cell": {"col": 1, "row": 1}})
    with pytest.raises(ValidationError):
        ctl.add_location("usbc", {"place": "nowhere"})


def test_same_spot_merges(ctl):
    view = ctl.add_location("usbc", {"place": "box", "qty": 2})
    assert len(view["locations"]) == 2
    box = [loc for loc in view["locations"] if loc["place"] == "box"][0]
    assert box["qty"] == 5


def test_move_location_into_existing_spot_merges(ctl):
    view = ctl.update_location("usbc", "l2", {"place": "box", "cell": None})
    assert len(view["locations"]) == 1
    assert view["locations"][0]["qty"] == 5


def test_step_qty_floors_at_zero(ctl):
    ctl.step_qty("usbc", "l1", -10)
    assert [loc["qty"] for loc in ctl.item("usbc")["locations"] if loc["id"] == "l1"] == [0]
    view = ctl.step_qty("hdmi", "l3", 1)
    assert view["locations"][0]["qty"] == 1


def test_new_item_with_location(ctl):
    view = ctl.save_item({"name": "Soldering iron", "category": "Tools",
                          "locations": [{"place": "left", "cell": "1,1", "qty": 1}]})
    assert view["locations"][0]["text"].endswith("1st from the right, 1st from the top")


def test_new_item_rejects_bad_location_and_saves_nothing(ctl):
    with pytest.raises(ValidationError):
        ctl.save_item({"name": "Ghost", "locations": [{"place": "nowhere"}]})
    assert "ghost" not in [i["id"] for i in ctl.items]


def test_place_cannot_go_inside_itself(ctl):
    with pytest.raises(ValidationError):
        ctl.save_place({"id": "left", "parent": "box", "cell": None})


def test_shrinking_a_wall_refuses_to_strand_things(ctl):
    with pytest.raises(ValidationError) as err:
        ctl.save_place({"id": "left", "cols": 10})
    assert "Black box with lid" in str(err.value)
    # Counting from the right, the box sits in the 3rd column from the left,
    # so dropping columns on the left end (beyond 14) is fine.
    ctl.save_place({"id": "left", "cols": 14})
    assert by_id(ctl)["left"]["cols"] == 14


def test_flipping_count_direction_renumbers(ctl):
    ctl.save_place({"id": "left", "count_cols_from": "left"})
    assert by_id(ctl)["box"]["cell"] == {"col": 3, "row": 2}
    hdmi = ctl.item("hdmi")["locations"][0]
    assert hdmi["cell"] == {"col": 3, "row": 2}
    assert "3rd from the left" in hdmi["text"]


def test_wall_with_contents_cannot_stop_being_a_wall(ctl):
    with pytest.raises(ValidationError):
        ctl.save_place({"id": "left", "kind": "area"})


def test_delete_box_moves_contents_into_its_compartment(ctl):
    result = ctl.delete_place("box")
    assert result["moved_items"] == 1
    loc = [loc for loc in ctl.item("usbc")["locations"] if loc["place"] == "left"][0]
    assert loc["cell"] == {"col": 14, "row": 2}


def test_delete_root_with_contents_refused(ctl):
    with pytest.raises(ValidationError):
        ctl.delete_place("cave")


def test_hand_edit_survives_next_tap(ctl):
    with open(ctl.path, encoding="utf-8") as handle:
        data = json.load(handle)
    data["items"].append({"name": "Hand-written", "locations": []})
    with open(ctl.path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    os.utime(ctl.path, (1, 1))  # make sure the mtime differs
    ctl.step_qty("usbc", "l1", 1)
    assert "hand_written" in [i["id"] for i in ctl.items]


def test_place_view_of_compartment(ctl):
    view = ctl.place("left", {"col": 14, "row": 2})
    assert [c["id"] for c in view["children"]] == ["box"]
    assert [i["item_id"] for i in view["items"]] == ["hdmi"]
    assert view["cell_label"] == "14th from the right, 2nd from the top"


def test_place_view_of_wall_has_grid(ctl):
    view = ctl.place("left")
    assert view["grid"]["cols"] == 16
    assert "14,2" in view["grid"]["cells"]


def test_seed_file_loads():
    with open(store.SEED_PATH, encoding="utf-8") as handle:
        data = store.normalize_data(json.load(handle))
    assert data["items"][0]["locations"]


# ---------------------------------------------------------------- http


def test_http_search(client):
    res = client.get("api/search?q=usbc")
    assert res.status_code == 200
    body = res.get_json()
    assert body["items"][0]["name"] == "USB-C cable"
    assert body["items"][0]["locations"][0]["text"]


def test_http_errors(client):
    assert client.get("api/items/nope").status_code == 404
    assert client.get("api/places/nope").status_code == 404
    res = client.post("api/items/usbc/locations", json={"place": "right", "cell": "99,1"})
    assert res.status_code == 400
    assert "no column 99" in res.get_json()["error"]


def test_http_full_flow(client):
    res = client.post("api/places", json={"name": "Red crate", "kind": "container",
                                          "parent": "right", "cell": "2,2"})
    assert res.status_code == 200
    crate = res.get_json()["id"]
    res = client.post("api/items", json={"name": "Multimeter",
                                         "locations": [{"place": crate, "qty": 1}]})
    item = res.get_json()
    assert "2nd from the left, 2nd from the top › Red crate" in item["locations"][0]["text"]
    loc = item["locations"][0]["id"]
    assert client.post("api/items/multimeter/locations/%s/step" % loc,
                       json={"delta": 1}).get_json()["total"] == 2
    assert client.delete("api/items/multimeter/locations/%s" % loc).status_code == 200
    assert client.delete("api/items/multimeter").status_code == 200
    assert client.get("api/items/multimeter").status_code == 404


def test_controller_unknown_item_raises(ctl):
    with pytest.raises(ItemNotFound):
        ctl.item("multimeter")


def test_http_index_uses_relative_urls(client):
    html = client.get("/").get_data(as_text=True)
    assert 'src="/' not in html and 'href="/' not in html
