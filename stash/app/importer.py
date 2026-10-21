"""Bring a batch of places and things into Stash.

The batch is JSON in any of these shapes, so whatever was written by hand or
produced from a photo goes in without reformatting:

    {"places": [...], "items": [...]}          same shape as stash.json
    {"spot": {"place": "...", "cell": ...},     everything in one spot; each
     "items": [{"name": ..., "qty": 3}, ...]}   item may still name its own
    [{"name": ...}, ...]                        just a list of things
    {"name": ...}                               one thing

Rules, chosen so that importing the same photo twice is visible rather than
silently doubling everything — the preview shows "added to existing":

- A place with an id that already exists is reused, never overwritten. A place
  without an id is reused when one with the same name sits in the same spot.
  Places may refer to each other in any order.
- A thing matches an existing one by id, or by name ignoring case, accents
  and punctuation ("USB-C cable" = "usb c cable"). A match gets the new spots
  added (same spot: the counts add up), missing category/notes filled in and
  tags merged. Anything else becomes a new thing.
- A spot that points at an unknown place or a compartment outside the wall is
  reported and left out. A thing whose every spot was bad is skipped rather
  than imported as "not put anywhere".

`run()` works on the dict it is given; the controller hands it a deep copy for
a preview and the real data to apply.
"""

from __future__ import annotations

from . import model, store
from .store import ValidationError


class ImportError_(ValidationError):
    """The batch itself is unusable (not JSON of a known shape)."""


def parse_text(text):
    """JSON text → Python, forgiving the way snippets get copied out of chat.

    A run of objects separated by commas ("{...},\n{...},") is not valid JSON
    on its own; it is read as a list. So is a trailing comma.
    """
    import json

    text = (text or "").strip()
    if not text:
        raise ImportError_("nothing to import")
    try:
        return json.loads(text)
    except ValueError as first:
        candidate = text.rstrip().rstrip(",")
        if not candidate.startswith("["):
            candidate = "[" + candidate + "]"
        try:
            return json.loads(candidate)
        except ValueError:
            raise ImportError_(
                "not valid JSON: %s (line %d, column %d)" % (first.msg, first.lineno, first.colno)
            )


def parse_payload(raw):
    if isinstance(raw, list):
        return {"places": [], "items": raw, "spot": None}
    if not isinstance(raw, dict):
        raise ImportError_("expected a JSON object or a list of things")
    if "items" not in raw and "places" not in raw:
        if raw.get("name"):
            return {"places": [], "items": [raw], "spot": None}
        raise ImportError_("found no \"items\" or \"places\" to import")
    places = raw.get("places") or []
    items = raw.get("items") or []
    if not isinstance(places, list) or not isinstance(items, list):
        raise ImportError_("\"places\" and \"items\" must be lists")
    return {"places": places, "items": items, "spot": raw.get("spot")}


def _name_key(name):
    return model.compact(name)


class _Run:
    def __init__(self, data):
        self.data = data
        self.places = data.setdefault("places", [])
        self.items = data.setdefault("items", [])
        self.idmap = {}  # id used in the batch -> real place id
        self.report = {
            "places_created": [],
            "places_reused": [],
            "items_created": [],
            "items_added": [],
            "skipped": [],
            "warnings": [],
        }

    # -- places ------------------------------------------------------------

    def by_id(self):
        return model.index(self.places)

    def resolve_place(self, ref):
        if not ref:
            return None
        ref = str(ref).strip()
        if ref in self.idmap:
            return self.idmap[ref]
        slug = store.slugify(ref, "place")
        if slug in self.idmap:
            return self.idmap[slug]
        known = self.by_id()
        if ref in known:
            return ref
        if slug in known:
            return slug
        return None

    def check_cell(self, place_id, cell_raw, what):
        """A parsed cell valid for place_id, or raise ValidationError."""
        cell = store.parse_cell(cell_raw)
        if not cell:
            return None
        place = self.by_id()[place_id]
        if place["kind"] != "grid":
            raise ValidationError("%s has no compartments" % place["name"])
        if not model.in_bounds(place, cell):
            raise ValidationError(
                "%s is %s × %s; there is no column %s, row %s"
                % (place["name"], place["cols"], place["rows"], cell["col"], cell["row"])
            )
        return cell

    def import_places(self, raw_places):
        pending = [p for p in raw_places if isinstance(p, dict)]
        for bad in (p for p in raw_places if not isinstance(p, dict)):
            self.report["skipped"].append({"name": str(bad), "reason": "not a place object"})
        while pending:
            progressed, waiting = False, []
            for raw in pending:
                parent_ref = raw.get("parent")
                parent = self.resolve_place(parent_ref) if parent_ref else None
                if parent_ref and parent is None:
                    waiting.append(raw)
                    continue
                progressed = True
                self.import_place(raw, parent)
            if not progressed:
                for raw in waiting:
                    self.report["skipped"].append({
                        "name": raw.get("name") or raw.get("id") or "?",
                        "reason": "inside an unknown place '%s'" % raw.get("parent"),
                    })
                break
            pending = waiting

    def import_place(self, raw, parent):
        name = str(raw.get("name") or "").strip()
        given_id = str(raw.get("id") or "").strip()
        known = self.by_id()
        if given_id and (given_id in known or store.slugify(given_id, "place") in known):
            real = given_id if given_id in known else store.slugify(given_id, "place")
            self.idmap[given_id] = real
            self.report["places_reused"].append({"name": known[real]["name"], "id": real})
            return
        if not name:
            self.report["skipped"].append({"name": given_id or "?", "reason": "place needs a name"})
            return
        try:
            cell = self.check_cell(parent, raw.get("cell"), name) if parent else None
        except ValidationError as err:
            self.report["skipped"].append({"name": name, "reason": str(err)})
            return
        # Same name in the same spot: that is the same box.
        if not given_id:
            for place in self.places:
                if (
                    (place.get("parent") or None) == parent
                    and model.same_cell(place.get("cell"), cell)
                    and _name_key(place["name"]) == _name_key(name)
                ):
                    self.idmap[name] = place["id"]
                    self.report["places_reused"].append({"name": place["name"], "id": place["id"]})
                    return
        clean = dict(raw)
        clean.pop("id", None)
        if given_id:
            clean["id"] = store.unique_id(given_id, set(known), "place")
        try:
            place = store.normalize_place(clean, set(known))
        except ValidationError as err:
            self.report["skipped"].append({"name": name, "reason": str(err)})
            return
        place["parent"], place["cell"] = parent, cell
        self.places.append(place)
        self.idmap[given_id or name] = place["id"]
        self.idmap[place["id"]] = place["id"]
        self.report["places_created"].append({
            "name": place["name"],
            "id": place["id"],
            "where": model.path_text(model.path(self.by_id(), place["id"])),
        })

    # -- things --------------------------------------------------------------

    def locations_for(self, raw, spot):
        if isinstance(raw.get("locations"), list):
            return raw["locations"]
        if raw.get("place"):
            return [{k: raw.get(k) for k in ("place", "cell", "qty", "note") if k in raw}]
        if spot:
            loc = dict(spot)
            if "qty" in raw:
                loc["qty"] = raw["qty"]
            if raw.get("note"):
                loc["note"] = raw["note"]
            return [loc]
        return []

    def clean_location(self, raw_loc):
        if not isinstance(raw_loc, dict):
            raise ValidationError("a spot must be an object")
        place = self.resolve_place(raw_loc.get("place"))
        if not place:
            raise ValidationError("unknown place '%s'" % raw_loc.get("place"))
        cell = self.check_cell(place, raw_loc.get("cell"), "")
        qty = store.parse_qty(raw_loc["qty"]) if "qty" in raw_loc else 1
        return {
            "id": store.new_location_id(),
            "place": place,
            "cell": cell,
            "qty": qty,
            "note": str(raw_loc.get("note") or "").strip(),
        }

    def find_item(self, raw):
        given = str(raw.get("id") or "").strip()
        if given:
            for item in self.items:
                if item["id"] in (given, store.slugify(given)):
                    return item
        key = _name_key(raw.get("name"))
        if not key:
            return None
        for item in self.items:
            if _name_key(item["name"]) == key:
                return item
        return None

    def import_items(self, raw_items, spot):
        for raw in raw_items:
            if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
                self.report["skipped"].append({
                    "name": (raw.get("id") if isinstance(raw, dict) else None) or "?",
                    "reason": "a thing needs a name",
                })
                continue
            name = raw["name"].strip()
            wanted = self.locations_for(raw, spot)
            locations, problems = [], []
            for raw_loc in wanted:
                try:
                    locations.append(self.clean_location(raw_loc))
                except ValidationError as err:
                    problems.append(str(err))
            if wanted and not locations:
                self.report["skipped"].append({"name": name, "reason": "; ".join(problems)})
                continue
            for problem in problems:
                self.report["warnings"].append({"name": name, "reason": "one spot left out: " + problem})

            existing = self.find_item(raw)
            if existing is None:
                clean = {k: v for k, v in raw.items() if k not in ("locations", "place", "cell", "qty", "note")}
                if clean.get("id"):
                    clean["id"] = store.unique_id(clean["id"], {i["id"] for i in self.items})
                try:
                    item = store.normalize_item(clean, {i["id"] for i in self.items})
                except ValidationError as err:
                    self.report["skipped"].append({"name": name, "reason": str(err)})
                    continue
                item["locations"] = []
                bucket = "items_created"
                self.items.append(item)
            else:
                item = existing
                bucket = "items_added"
                if not item.get("category") and raw.get("category"):
                    item["category"] = str(raw["category"]).strip()
                if not item.get("notes") and raw.get("notes"):
                    item["notes"] = str(raw["notes"]).strip()
                extra = store.normalize_item({"name": name, "tags": raw.get("tags")})["tags"]
                item["tags"] = sorted(set(item.get("tags") or []) | set(extra))
            for loc in locations:
                model.merge_location(item["locations"], loc)
            by_id = self.by_id()
            self.report[bucket].append({
                "name": name,
                "id": item["id"],
                "matched": None if existing is None else existing["name"],
                "where": [
                    model.path_text(model.path(by_id, loc["place"], loc.get("cell")))
                    + ("" if loc.get("qty") is None else " ×%d" % loc["qty"])
                    for loc in locations
                ],
            })


def run(data, payload, default_spot=None):
    """Import into `data` (mutated) and return what happened."""
    batch = parse_payload(payload)
    job = _Run(data)
    job.import_places(batch["places"])
    spot = batch["spot"] or default_spot or None
    if spot is not None and not isinstance(spot, dict):
        raise ImportError_("\"spot\" must be an object like {\"place\": \"...\"}")
    job.import_items(batch["items"], spot)
    report = job.report
    report["counts"] = {
        "places_created": len(report["places_created"]),
        "items_created": len(report["items_created"]),
        "items_added": len(report["items_added"]),
        "skipped": len(report["skipped"]),
        "warnings": len(report["warnings"]),
    }
    report["changes"] = (
        report["counts"]["places_created"]
        + report["counts"]["items_created"]
        + report["counts"]["items_added"]
    )
    return report
