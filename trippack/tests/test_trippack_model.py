"""Tests for the packing engine — no disk, no HTTP."""

import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import model, store  # noqa: E402


CATALOG = [
    {"id": "camera", "name": "Camera", "category": "photo", "tags": ["photography"],
     "suggests": ["batteries", "lens", "bag"], "always": False, "notes": ""},
    {"id": "batteries", "name": "Spare batteries", "category": "photo", "tags": [],
     "suggests": ["charger"], "always": False, "notes": ""},
    {"id": "charger", "name": "Charger", "category": "photo", "tags": [],
     "suggests": [], "always": False, "notes": ""},
    {"id": "lens", "name": "Wide lens", "category": "photo", "tags": [],
     "suggests": ["cloth"], "always": False, "notes": ""},
    {"id": "cloth", "name": "Lens cloth", "category": "photo", "tags": [],
     "suggests": [], "always": False, "notes": ""},
    {"id": "bag", "name": "Camera bag", "category": "photo", "tags": [],
     "suggests": [], "always": False, "notes": ""},
    {"id": "boots", "name": "Hiking boots", "category": "outdoors", "tags": ["hiking"],
     "suggests": ["socks"], "always": False, "notes": ""},
    {"id": "socks", "name": "Hiking socks", "category": "outdoors", "tags": [],
     "suggests": [], "always": False, "notes": ""},
    {"id": "passport", "name": "Passport", "category": "papers", "tags": [],
     "suggests": [], "always": True, "notes": ""},
    {"id": "swimwear", "name": "Swimwear", "category": "water", "tags": ["swimming"],
     "suggests": [], "always": False, "notes": ""},
]

TRIP = {
    "id": "trip", "name": "Trip", "start": "2026-09-17", "end": "2026-09-19",
    "days": [
        {"date": "2026-09-17", "title": "Train", "tags": ["night_train"], "notes": ""},
        {"date": "2026-09-18", "title": "Hike", "tags": ["hiking", "photography"], "notes": ""},
        {"date": "2026-09-19", "title": "Lake", "tags": ["swimming", "photography"], "notes": ""},
    ],
    "packing": [], "dismissed": [],
}


@pytest.fixture
def trip():
    return copy.deepcopy(TRIP)


# -- adding ---------------------------------------------------------------

def test_add_item_is_idempotent_but_collects_reasons(trip):
    _, created = model.add_item(trip, "camera", {"kind": "manual"})
    assert created is True
    _, created_again = model.add_item(
        trip, "camera", {"kind": "day", "date": "2026-09-18", "tag": "photography"}
    )
    assert created_again is False
    assert len(trip["packing"]) == 1
    assert len(trip["packing"][0]["reasons"]) == 2


def test_identical_reason_is_not_recorded_twice(trip):
    model.add_item(trip, "camera", {"kind": "manual"})
    model.add_item(trip, "camera", {"kind": "manual"})
    assert len(model.entry_for(trip, "camera")["reasons"]) == 1


def test_adding_a_dismissed_item_clears_the_dismissal(trip):
    model.dismiss(trip, "boots")
    assert model.is_dismissed(trip, "boots")
    model.add_item(trip, "boots", {"kind": "manual"})
    assert not model.is_dismissed(trip, "boots")


# -- the suggestion graph -------------------------------------------------

def test_suggestions_are_one_level_and_skip_what_is_packed(trip):
    model.add_item(trip, "camera")
    assert model.suggestions_for(CATALOG, trip, "camera") == ["batteries", "lens", "bag"]
    model.add_item(trip, "lens")
    assert model.suggestions_for(CATALOG, trip, "camera") == ["batteries", "bag"]


def test_suggestions_cascade_one_step_at_a_time(trip):
    model.add_item(trip, "camera")
    first = model.suggestions_for(CATALOG, trip, "camera")
    assert "charger" not in first          # not offered until batteries are accepted
    model.add_item(trip, "batteries", {"kind": "suggested_by", "item_id": "camera"})
    assert model.suggestions_for(CATALOG, trip, "batteries") == ["charger"]


def test_dismissed_items_stop_being_suggested(trip):
    model.add_item(trip, "camera")
    model.dismiss(trip, "bag")
    assert "bag" not in model.suggestions_for(CATALOG, trip, "camera")
    assert "bag" in model.suggestions_for(CATALOG, trip, "camera", include_dismissed=True)


def test_chain_survives_a_cycle():
    looped = copy.deepcopy(CATALOG)
    by_id = model.index_items(looped)
    by_id["charger"]["suggests"] = ["camera"]
    chain = model.chain_from(looped, "camera")
    assert "charger" in chain
    assert len(chain) < 20  # it terminated rather than spiralling


def test_unknown_suggestion_targets_are_ignored(trip):
    catalog = copy.deepcopy(CATALOG)
    model.index_items(catalog)["camera"]["suggests"] = ["ghost", "bag"]
    assert model.suggestions_for(catalog, trip, "camera") == ["bag"]


# -- itinerary ------------------------------------------------------------

def test_itinerary_pulls_items_by_day_tag(trip):
    candidates = model.itinerary_candidates(CATALOG, trip)
    assert set(candidates) == {"camera", "boots", "swimwear"}
    reasons = candidates["camera"]
    assert len(reasons) == 2          # tagged photography on two separate days
    assert {r["date"] for r in reasons} == {"2026-09-18", "2026-09-19"}


def test_itinerary_can_be_narrowed_to_one_day(trip):
    candidates = model.itinerary_candidates(CATALOG, trip, date="2026-09-19")
    assert set(candidates) == {"camera", "swimwear"}


def test_itinerary_skips_what_is_already_on_the_list(trip):
    model.add_item(trip, "boots")
    assert "boots" not in model.itinerary_candidates(CATALOG, trip)


def test_apply_candidates_keeps_every_reason(trip):
    model.apply_candidates(trip, model.itinerary_candidates(CATALOG, trip))
    assert len(model.entry_for(trip, "camera")["reasons"]) == 2
    assert len(trip["packing"]) == 3


def test_essentials_are_offered_once(trip):
    assert model.essential_candidates(CATALOG, trip) == ["passport"]
    model.add_item(trip, "passport", {"kind": "essential"})
    assert model.essential_candidates(CATALOG, trip) == []


# -- state and read models ------------------------------------------------

def test_toggle_and_progress(trip):
    model.add_item(trip, "camera")
    model.add_item(trip, "boots")
    assert model.progress(trip)["pct"] == 0
    model.toggle_packed(trip, "camera")
    assert model.progress(trip)["packed"] == 1
    assert model.progress(trip)["pct"] == 50
    model.toggle_packed(trip, "camera")
    assert model.progress(trip)["packed"] == 0


def test_skipped_items_do_not_drag_the_percentage_down(trip):
    model.add_item(trip, "camera")
    model.add_item(trip, "boots")
    model.set_state(trip, "camera", "packed")
    model.set_state(trip, "boots", "skipped")
    progress = model.progress(trip)
    assert progress == {"total": 2, "packed": 1, "todo": 0, "skipped": 1, "pct": 100}


def test_set_state_rejects_nonsense(trip):
    model.add_item(trip, "camera")
    with pytest.raises(ValueError):
        model.set_state(trip, "camera", "maybe")


def test_explain_reads_back_the_trail(trip):
    model.add_item(trip, "camera", {"kind": "day", "date": "2026-09-18", "tag": "photography"})
    model.add_item(trip, "batteries", {"kind": "suggested_by", "item_id": "camera"})
    assert model.explain(trip, "camera", CATALOG) == ["Fri 18 Sep — Hike needs photography"]
    assert model.explain(trip, "batteries", CATALOG) == ["Goes with Camera"]


def test_packing_view_flags_items_dropped_from_the_catalogue(trip):
    model.add_item(trip, "camera")
    rows = model.packing_view([c for c in CATALOG if c["id"] != "camera"], trip)
    assert rows[0]["missing"] is True


def test_day_view_counts_what_is_still_outstanding(trip):
    days = model.day_view(CATALOG, trip)
    hike = [d for d in days if d["date"] == "2026-09-18"][0]
    assert hike["candidates"] == 2          # boots and camera
    model.apply_candidates(trip, model.itinerary_candidates(CATALOG, trip))
    hike = [d for d in model.day_view(CATALOG, trip) if d["date"] == "2026-09-18"][0]
    assert hike["candidates"] == 0
    assert hike["unpacked"] == 2            # on the list, not yet in the bag


def test_summary_shape(trip):
    summary = model.summary(CATALOG, trip)
    assert summary["trip_id"] == "trip"
    assert summary["suggestions_waiting"] == 4   # three tagged items plus the passport


# -- store ----------------------------------------------------------------

def test_normalize_item_slugifies_and_cleans_tags():
    item = store.normalize_item({"name": "Wide Lens", "tags": " Photo , photo ,HIKING "})
    assert item["id"] == "wide_lens"
    assert item["tags"] == ["hiking", "photo"]


def test_normalize_rejects_a_nameless_item():
    with pytest.raises(store.ValidationError):
        store.normalize_item({"tags": ["x"]})


def test_normalize_rejects_a_bad_date():
    with pytest.raises(store.ValidationError):
        store.normalize_day({"date": "17/09/2026"})


def test_normalize_data_falls_back_to_the_first_trip():
    data = store.normalize_data({"trips": [dict(TRIP)], "active_trip": "nope", "items": CATALOG})
    assert data["active_trip"] == "trip"


def test_round_trip_through_disk(tmp_path):
    path = str(tmp_path / "trippack.json")
    data = store.normalize_data({"items": CATALOG, "trips": [copy.deepcopy(TRIP)]})
    model.add_item(data["trips"][0], "camera", {"kind": "manual"})
    store.write(data, path)
    assert store.read(path)["trips"][0]["packing"][0]["item_id"] == "camera"


def test_seed_file_is_consistent():
    data = store.read(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "seed", "default.json"))
    assert store.dangling_suggestions(data) == {}
    trip = data["trips"][0]
    assert len(trip["days"]) == 10
    # every day tag should be able to pull at least one item
    unmatched = []
    for day in trip["days"]:
        matched = any(set(day["tags"]) & set(item["tags"]) for item in data["items"])
        if not matched:
            unmatched.append(day["date"])
    assert unmatched == []


# ---------------------------------------------------------------- row hints

def test_row_hint_names_the_item_that_brought_it():
    items = model.index_items(CATALOG)
    assert model.row_hint([{"kind": "suggested_by", "item_id": "camera"}], items) == "Camera"


def test_row_hint_shortens_a_day_and_counts_the_rest():
    items = model.index_items(CATALOG)
    hint = model.row_hint(
        [
            {"kind": "day", "date": "2026-09-19", "tag": "beach"},
            {"kind": "day", "date": "2026-09-21", "tag": "hiking"},
        ],
        items,
    )
    assert hint == "19 Sep +1"


def test_row_hint_is_empty_for_something_you_added_yourself():
    assert model.row_hint([{"kind": "manual"}], model.index_items(CATALOG)) == ""


def test_packing_view_carries_the_hint():
    trip = copy.deepcopy(TRIP)
    model.add_item(trip, "batteries", {"kind": "suggested_by", "item_id": "camera"})
    row = model.packing_view(CATALOG, trip)[0]
    assert row["hint"] == "Camera"
