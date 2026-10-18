"""The one object that owns Stash's state.

Everything the web layer does goes through here, under a lock, and every
mutation saves. Hand edits to stash.json are picked up before each call, so a
tap in the UI never writes a stale copy over them. A `dirty` Event is set on
every change for a future MQTT publisher.
"""

from __future__ import annotations

import functools
import logging
import threading

from . import model, store
from .store import ValidationError

LOG = logging.getLogger("stash.controller")


class PlaceNotFound(KeyError):
    pass


class ItemNotFound(KeyError):
    pass


class LocationNotFound(KeyError):
    pass


def guarded(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            self._reload_if_changed()
            return method(self, *args, **kwargs)

    return wrapper


class Controller:
    def __init__(self, path=store.DEFAULT_PATH, seed_path=store.SEED_PATH):
        self.path = path
        self._lock = threading.RLock()
        self.dirty = threading.Event()
        self._data = store.load_or_seed(path, seed_path)
        self._mtime = store.mtime(path)

    # -- internals ---------------------------------------------------------

    def _save(self):
        store.write(self._data, self.path)
        self._mtime = store.mtime(self.path)
        self.dirty.set()

    def _reload_if_changed(self):
        current = store.mtime(self.path)
        if current and current != self._mtime:
            try:
                self._data = store.read(self.path)
                self._mtime = current
                self.dirty.set()
                LOG.info("Reloaded %s after an external edit", self.path)
            except ValueError as err:
                LOG.warning("Ignoring unreadable %s: %s", self.path, err)

    @property
    def places(self):
        return self._data["places"]

    @property
    def items(self):
        return self._data["items"]

    def _place(self, place_id):
        for place in self.places:
            if place["id"] == place_id:
                return place
        raise PlaceNotFound(place_id)

    def _item(self, item_id):
        for item in self.items:
            if item["id"] == item_id:
                return item
        raise ItemNotFound(item_id)

    def _location(self, item, location_id):
        for loc in item["locations"]:
            if loc["id"] == location_id:
                return loc
        raise LocationNotFound(location_id)

    def _spot(self, place_id, cell):
        """Validate "put it here": the place exists and the cell fits it."""
        if not place_id:
            raise ValidationError("choose a place")
        try:
            place = self._place(place_id)
        except PlaceNotFound:
            raise ValidationError("no such place: %s" % place_id)
        cell = store.parse_cell(cell)
        if cell:
            if place["kind"] != "grid":
                raise ValidationError("%s has no compartments" % place["name"])
            if not model.in_bounds(place, cell):
                raise ValidationError(
                    "%s is %d × %d; there is no column %d, row %d"
                    % (place["name"], place["cols"], place["rows"], cell["col"], cell["row"])
                )
        return place, cell

    def _view(self, item):
        return model.item_view(model.index(self.places), item)

    @staticmethod
    def _merge_into(locations, loc):
        """Add a location, or fold it into one already at the same spot."""
        for other in locations:
            if other is loc:
                continue
            if other["place"] == loc["place"] and model.same_cell(other["cell"], loc["cell"]):
                if other["qty"] is not None and loc["qty"] is not None:
                    other["qty"] += loc["qty"]
                if loc["note"] and loc["note"] not in other["note"]:
                    other["note"] = (other["note"] + "; " + loc["note"]).strip("; ")
                if loc in locations:
                    locations.remove(loc)
                return other
        if loc not in locations:
            locations.append(loc)
        return loc

    # -- reads -------------------------------------------------------------

    @guarded
    def state(self):
        by_id = model.index(self.places)
        items = [model.item_view(by_id, item) for item in self.items]
        items.sort(key=lambda i: model.fold(i["name"]))
        return {
            "places": [model.place_summary(self.places, self.items, p, by_id) for p in self.places],
            "items": items,
            "categories": self.categories(),
            "tags": sorted({t for item in self.items for t in item["tags"]}),
            "summary": self._summary(),
        }

    def categories(self):
        return sorted({i["category"] for i in self.items if i["category"]}, key=str.lower)

    def _summary(self):
        return {
            "items": len(self.items),
            "locations": sum(len(i["locations"]) for i in self.items),
            "places": len(self.places),
            "unplaced": sum(1 for i in self.items if not i["locations"]),
        }

    @guarded
    def summary(self):
        return self._summary()

    @guarded
    def search(self, query, limit=50):
        found = model.search(self.places, self.items, query, limit)
        by_id = model.index(self.places)
        return {
            "query": query,
            "items": [model.item_view(by_id, item) for item in found["items"]],
            "places": [
                dict(model.place_summary(self.places, self.items, p, by_id),
                     path=model.path_text(model.path(by_id, p["id"])))
                for p in found["places"]
            ],
        }

    @guarded
    def item(self, item_id):
        return self._view(self._item(item_id))

    @guarded
    def place(self, place_id, cell=None):
        self._place(place_id)
        place, cell = self._spot(place_id, cell)
        return model.place_view(self.places, self.items, place["id"], cell)

    # -- places ------------------------------------------------------------

    @guarded
    def save_place(self, raw):
        raw = dict(raw or {})
        existing = None
        if raw.get("id"):
            try:
                existing = self._place(raw["id"])
            except PlaceNotFound:
                existing = None
        if existing is not None:
            merged = dict(existing)
            merged.update({k: v for k, v in raw.items() if k != "id"})
            merged["id"] = existing["id"]
            place = store.normalize_place(merged)
        else:
            raw.pop("id", None)
            place = store.normalize_place(raw, {p["id"] for p in self.places})

        # Where it sits.
        if place["parent"]:
            if existing is not None and (
                place["parent"] == existing["id"]
                or place["parent"] in model.descendants(self.places, existing["id"])
            ):
                raise ValidationError("a place cannot sit inside itself")
            _, place["cell"] = self._spot(place["parent"], raw.get("cell", place["cell"]))
        else:
            place["cell"] = None

        if existing is not None:
            self._reshape(existing, place)
            existing.clear()
            existing.update(place)
            place = existing
        else:
            self.places.append(place)
        self._save()
        return model.place_summary(self.places, self.items, place)

    def _reshape(self, old, new):
        """Apply a wall's new size or numbering to everything placed on it."""
        on_wall = [p for p in self.places if p.get("parent") == old["id"] and p.get("cell")]
        on_wall_locs = [
            (item, loc)
            for item in self.items
            for loc in item["locations"]
            if loc["place"] == old["id"] and loc.get("cell")
        ]
        if not on_wall and not on_wall_locs:
            return
        if old["kind"] == "grid" and new["kind"] != "grid":
            raise ValidationError(
                "%s still has things in its compartments; move them first" % old["name"]
            )
        if old["kind"] != "grid":
            return
        moved, outside = [], []
        for row in on_wall:
            cell = model.renumber(old, new, row["cell"])
            moved.append((row, cell))
            if not model.in_bounds(new, cell):
                outside.append(row["name"])
        for item, loc in on_wall_locs:
            cell = model.renumber(old, new, loc["cell"])
            moved.append((loc, cell))
            if not model.in_bounds(new, cell):
                outside.append(item["name"])
        if outside:
            names = sorted(set(outside), key=str.lower)
            raise ValidationError(
                "That would leave %s outside the wall. Move %s first."
                % (", ".join(names[:5]) + (" and more" if len(names) > 5 else ""),
                   "it" if len(names) == 1 else "them")
            )
        for row, cell in moved:
            row["cell"] = cell

    @guarded
    def delete_place(self, place_id):
        """Remove a place; whatever was inside moves up to where it stood."""
        place = self._place(place_id)
        parent_id = place.get("parent")
        children = [p for p in self.places if p.get("parent") == place_id]
        holders = [
            (item, loc) for item in self.items for loc in item["locations"]
            if loc["place"] == place_id
        ]
        if not parent_id and (children or holders):
            raise ValidationError(
                "%s still holds things and has nowhere to pass them to. "
                "Move or delete them first." % place["name"]
            )
        parent = None
        if parent_id:
            try:
                parent = self._place(parent_id)
            except PlaceNotFound:
                parent = None
        landing_cell = place.get("cell") if parent and parent["kind"] == "grid" else None
        for child in children:
            child["parent"] = parent_id
            child["cell"] = landing_cell
        for item, loc in holders:
            loc["place"] = parent_id
            loc["cell"] = landing_cell
            self._merge_into(item["locations"], loc)
        self.places.remove(place)
        self._save()
        return {"moved_places": len(children), "moved_items": len(holders), "to": parent_id}

    # -- items -------------------------------------------------------------

    @guarded
    def save_item(self, raw):
        raw = dict(raw or {})
        existing = None
        if raw.get("id"):
            try:
                existing = self._item(raw["id"])
            except ItemNotFound:
                existing = None
        if existing is not None:
            merged = dict(existing)
            merged.update({k: v for k, v in raw.items() if k not in ("id", "locations")})
            merged["id"] = existing["id"]
            merged["locations"] = existing["locations"]
            item = store.normalize_item(merged)
            existing.clear()
            existing.update(item)
            item = existing
        else:
            new_locations = raw.pop("locations", None) or []
            raw.pop("id", None)
            raw["locations"] = []
            item = store.normalize_item(raw, {i["id"] for i in self.items})
            for raw_loc in new_locations:
                self._add_location(item, raw_loc)
            self.items.append(item)
        self._save()
        return self._view(item)

    @guarded
    def delete_item(self, item_id):
        self.items.remove(self._item(item_id))
        self._save()

    def _add_location(self, item, raw):
        raw = raw or {}
        place, cell = self._spot(raw.get("place"), raw.get("cell"))
        qty = store.parse_qty(raw.get("qty", 1))
        loc = {
            "id": store.new_location_id(),
            "place": place["id"],
            "cell": cell,
            "qty": qty,
            "note": str(raw.get("note") or "").strip(),
        }
        return self._merge_into(item["locations"], loc)

    @guarded
    def add_location(self, item_id, raw):
        item = self._item(item_id)
        self._add_location(item, raw)
        self._save()
        return self._view(item)

    @guarded
    def update_location(self, item_id, location_id, raw):
        """Move it, recount it, or change its note."""
        item = self._item(item_id)
        loc = self._location(item, location_id)
        raw = raw or {}
        if "place" in raw or "cell" in raw:
            place, cell = self._spot(raw.get("place", loc["place"]), raw.get("cell"))
            loc["place"], loc["cell"] = place["id"], cell
        if "qty" in raw:
            loc["qty"] = store.parse_qty(raw["qty"])
        if "note" in raw:
            loc["note"] = str(raw.get("note") or "").strip()
        self._merge_into(item["locations"], loc)
        self._save()
        return self._view(item)

    @guarded
    def step_qty(self, item_id, location_id, delta):
        item = self._item(item_id)
        loc = self._location(item, location_id)
        delta = int(delta)
        if loc["qty"] is None:
            loc["qty"] = max(0, delta) if delta > 0 else 0
        else:
            loc["qty"] = max(0, loc["qty"] + delta)
        self._save()
        return self._view(item)

    @guarded
    def remove_location(self, item_id, location_id):
        item = self._item(item_id)
        item["locations"].remove(self._location(item, location_id))
        self._save()
        return self._view(item)
