"""Import: the shapes it accepts, how it matches, what a preview promises."""

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from app import importer  # noqa: E402
from app.controller import Controller  # noqa: E402
from app.store import SEED_PATH, ValidationError  # noqa: E402
from app.web.server import create_app  # noqa: E402

PHOTO = os.path.join(HERE, "fixtures", "left-kallax-5-7.json")

# What a photo of one compartment came back as, pasted straight out of chat:
# objects separated by commas, no surrounding list.
SNIPPET = """
{"name": "Sky Team", "category": "Board games", "tags": ["co-op"],
 "locations": [{"place": "right_kallax", "cell": {"col": 4, "row": 2}, "qty": 1}]},

{"name": "Kingdomino", "category": "Board games",
 "locations": [{"place": "right_kallax", "cell": {"col": 4, "row": 2}, "qty": 1}]},
"""


@pytest.fixture()
def ctl(tmp_path):
    return Controller(path=str(tmp_path / "stash.json"), seed_path=SEED_PATH)


def names(rows):
    return [row["name"] for row in rows]


def test_photo_file_imports_whole(ctl):
    with open(PHOTO, encoding="utf-8") as handle:
        batch = json.load(handle)
    report = ctl.import_batch(batch, dry_run=False)
    assert report["counts"]["places_created"] == 1
    assert report["counts"]["items_created"] == len(batch["items"])
    assert report["counts"]["skipped"] == 0
    found = ctl.search("seinfeld")["items"][0]
    assert found["locations"][0]["text"].endswith("6th from the right, 2nd from the top")
    top = ctl.search("talisker")["items"][0]
    assert top["locations"][0]["text"] == "Man cave › On top of the left Kallax"


def test_preview_changes_nothing(ctl):
    before = open(ctl.path, encoding="utf-8").read()
    report = ctl.import_batch(SNIPPET)
    assert report["dry_run"] and report["counts"]["items_created"] == 2
    assert open(ctl.path, encoding="utf-8").read() == before
    assert not ctl.search("kingdomino")["items"]


def test_snippet_text_from_chat_is_accepted(ctl):
    report = ctl.import_batch(SNIPPET, dry_run=False)
    assert names(report["items_created"]) == ["Sky Team", "Kingdomino"]


def test_reimport_adds_to_existing_instead_of_duplicating(ctl):
    ctl.import_batch(SNIPPET, dry_run=False)
    report = ctl.import_batch(SNIPPET, dry_run=False)
    assert report["counts"]["items_created"] == 0
    assert report["counts"]["items_added"] == 2
    sky = ctl.search("sky team")["items"]
    assert len(sky) == 1 and sky[0]["locations"][0]["qty"] == 2


def test_name_match_ignores_case_and_punctuation(ctl):
    report = ctl.import_batch(
        {"spot": {"place": "left_kallax", "cell": [1, 1]},
         "items": [{"name": "usb c Cable", "qty": 2, "tags": ["spare"]}]},
        dry_run=False)
    assert report["items_added"][0]["matched"] == "USB-C cable"
    cable = ctl.search("usbc")["items"][0]
    assert len(cable["locations"]) == 3
    assert "spare" in cable["tags"] and "usb" in cable["tags"]


def test_spot_shape_puts_everything_in_one_place(ctl):
    report = ctl.import_batch(
        {"spot": {"place": "black_box_with_lid"},
         "items": [{"name": "HDMI cable", "qty": 2}, {"name": "Lightning cable"}]},
        dry_run=False)
    assert report["counts"]["items_created"] == 2
    hdmi = ctl.search("hdmi")["items"][0]
    assert hdmi["locations"][0]["qty"] == 2
    assert hdmi["locations"][0]["text"].endswith("Black box with lid")


def test_default_spot_from_the_ui_fills_in_missing_spots(ctl):
    report = ctl.import_batch([{"name": "Drill"}], {"place": "behind_left_kallax"}, dry_run=False)
    assert report["items_created"][0]["where"] == ["Man cave › Behind the left Kallax ×1"]


def test_places_in_any_order_and_reuse_by_name(ctl):
    batch = {
        "places": [
            {"id": "inner", "name": "Cable pouch", "kind": "container", "parent": "crate"},
            {"id": "crate", "name": "Red crate", "kind": "container",
             "parent": "right_kallax", "cell": "2,3"},
        ],
        "items": [{"name": "Jumper wires", "locations": [{"place": "inner"}]}],
    }
    report = ctl.import_batch(batch, dry_run=False)
    assert report["counts"]["places_created"] == 2
    wires = ctl.search("jumper")["items"][0]
    assert wires["locations"][0]["text"] == (
        "Man cave › Right Kallax › 2nd from the left, 3rd from the top › Red crate › Cable pouch")
    # The same crate again, without ids: recognised, not duplicated.
    again = ctl.import_batch({"places": [
        {"name": "red crate", "kind": "container", "parent": "right_kallax", "cell": [2, 3]}]},
        dry_run=False)
    assert again["counts"]["places_created"] == 0
    assert len(again["places_reused"]) == 1


def test_existing_place_id_is_reused_not_overwritten(ctl):
    report = ctl.import_batch({"places": [
        {"id": "left_kallax", "name": "Renamed!", "kind": "area"}]}, dry_run=False)
    assert report["counts"]["places_created"] == 0
    assert ctl.place("left_kallax")["place"]["name"] == "Left Kallax"


def test_bad_spots_are_reported(ctl):
    report = ctl.import_batch([
        {"name": "Ghost", "locations": [{"place": "nowhere"}]},
        {"name": "Too far", "locations": [{"place": "left_kallax", "cell": [99, 1]}]},
        {"name": "Half right", "locations": [{"place": "nowhere"}, {"place": "man_cave"}]},
        {"notes": "no name"},
        {"name": "Orphan box"},
    ], dry_run=False)
    skipped = {row["name"]: row["reason"] for row in report["skipped"]}
    assert "unknown place 'nowhere'" in skipped["Ghost"]
    assert "no column 99" in skipped["Too far"]
    assert "?" in skipped
    assert names(report["warnings"]) == ["Half right"]
    # A thing with no spot at all is fine: "not put anywhere yet".
    assert set(names(report["items_created"])) == {"Half right", "Orphan box"}


def test_place_under_unknown_parent_is_skipped(ctl):
    report = ctl.import_batch({"places": [{"name": "Lost box", "parent": "nope"}]})
    assert report["skipped"][0]["reason"] == "inside an unknown place 'nope'"


def test_unusable_input(ctl):
    with pytest.raises(ValidationError):
        ctl.import_batch("this is not json")
    with pytest.raises(ValidationError):
        ctl.import_batch({"hello": 1})
    with pytest.raises(ValidationError):
        importer.parse_text("   ")


def test_http_import(ctl):
    client = create_app(ctl).test_client()
    res = client.post("api/import", json={"text": SNIPPET})
    assert res.status_code == 200 and res.get_json()["dry_run"] is True
    res = client.post("api/import", json={"text": SNIPPET, "dry_run": False})
    assert res.get_json()["counts"]["items_created"] == 2
    res = client.post("api/import", json={"text": "{nope"})
    assert res.status_code == 400 and "not valid JSON" in res.get_json()["error"]
    assert client.post("api/import", json={}).status_code == 400
