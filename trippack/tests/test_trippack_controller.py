"""Tests for the controller and the HTTP layer — temp files, no Supervisor."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.controller import Controller, ItemNotFound, TripNotFound  # noqa: E402
from app.web.server import create_app  # noqa: E402


SEED = {
    "active_trip": "trip",
    "items": [
        {"id": "camera", "name": "Camera", "category": "photo",
         "tags": ["photography"], "suggests": ["cloth"]},
        {"id": "cloth", "name": "Lens cloth", "category": "photo"},
        {"id": "boots", "name": "Boots", "category": "outdoors", "tags": ["hiking"]},
        {"id": "passport", "name": "Passport", "category": "papers", "always": True},
    ],
    "trips": [
        {
            "id": "trip",
            "name": "Trip",
            "days": [{"date": "2026-09-18", "title": "Walk", "tags": ["hiking"]}],
            "packing": [],
            "dismissed": [],
        }
    ],
}


@pytest.fixture()
def paths(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(SEED), encoding="utf-8")
    return str(tmp_path / "trippack.json"), str(seed)


@pytest.fixture()
def controller(paths):
    data_file, seed = paths
    return Controller(path=data_file, seed_path=seed)


def touch_later(path):
    """Move the mtime on so the controller cannot miss the change."""
    stamp = os.path.getmtime(path) + 10
    os.utime(path, (stamp, stamp))


def hand_edit(path, mutate):
    data = json.loads(open(path, encoding="utf-8").read())
    mutate(data)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    touch_later(path)


# ---------------------------------------------------------------- seeding

def test_first_run_writes_the_data_file(paths):
    data_file, seed = paths
    assert not os.path.exists(data_file)
    controller = Controller(path=data_file, seed_path=seed)
    assert os.path.exists(data_file)
    assert len(controller.catalog) == 4


# ---------------------------------------------------------------- hot reload

def test_state_picks_up_a_hand_edit(controller):
    hand_edit(controller.path, lambda d: d["items"].append({"id": "kite", "name": "Kite"}))
    assert any(i["id"] == "kite" for i in controller.state()["catalog"])


def test_a_mutation_does_not_clobber_a_hand_edit(controller):
    """The regression this file exists for.

    Someone edits trippack.json in the File editor while the page is open, then
    taps an item. The tap must not write our stale copy back over their edit.
    """
    hand_edit(controller.path, lambda d: d["items"].append({"id": "kite", "name": "Kite"}))
    controller.add("camera")  # a write that never read first, before the fix
    on_disk = json.loads(open(controller.path, encoding="utf-8").read())
    assert any(i["id"] == "kite" for i in on_disk["items"])
    assert any(e["item_id"] == "camera" for e in on_disk["trips"][0]["packing"])


def test_an_unreadable_file_is_ignored_rather_than_crashing(controller):
    with open(controller.path, "w", encoding="utf-8") as handle:
        handle.write("{ not json")
    touch_later(controller.path)
    assert controller.state()["catalog"]  # still serving the last good copy


# ---------------------------------------------------------------- lookups

def test_unknown_trip_raises(controller):
    with pytest.raises(TripNotFound):
        controller.summary("nope")


def test_unknown_item_raises(controller):
    with pytest.raises(ItemNotFound):
        controller.add("nope")
    with pytest.raises(ItemNotFound):
        controller.toggle("nope")


# ---------------------------------------------------------------- http

@pytest.fixture()
def client(controller):
    return create_app(controller).test_client()


def test_packing_an_unknown_item_is_a_404(client):
    res = client.post("/api/pack", json={"item_id": "nope"})
    assert res.status_code == 404
    assert "nope" in res.get_json()["error"]


def test_an_unknown_trip_id_is_a_404_not_an_empty_page(client):
    assert client.get("/api/state?trip=nope").status_code == 404
    assert client.get("/api/state").status_code == 200


def test_pack_returns_what_goes_with_it(client):
    body = client.post("/api/pack", json={"item_id": "camera"}).get_json()
    assert body["added"] is True
    assert [s["item_id"] for s in body["suggestions"]] == ["cloth"]


def test_pull_takes_the_itinerary_and_the_essentials(client):
    body = client.post("/api/pull", json={}).get_json()
    assert sorted(body["added"]) == ["boots", "passport"]
    rows = client.get("/api/state").get_json()["active_trip"]["packing"]
    why = {r["item_id"]: r["why"] for r in rows}
    assert why["passport"] == ["Always packed"]
    assert "hiking" in why["boots"][0]


def test_health(client):
    assert client.get("/health").get_json() == {"ok": True}
