"""The one object that owns TripPack's state.

Everything the web layer does goes through here, under a lock, and every
mutation saves. A `dirty` Event is set on every change so a future MQTT
publisher can wake up immediately instead of polling.
"""

from __future__ import annotations

import functools
import logging
import threading

from . import model, store

LOG = logging.getLogger("trippack.controller")


class TripNotFound(KeyError):
    pass


class ItemNotFound(KeyError):
    pass


def guarded(method):
    """Take the lock and pick up any hand edit before the method runs.

    Every public method goes through here. Without the reload, a tap in the UI
    would write our stale in-memory copy over an edit someone had just made to
    trippack.json by hand.
    """

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
        """Pick up hand edits to trippack.json without a restart."""
        current = store.mtime(self.path)
        if current and current != self._mtime:
            try:
                self._data = store.read(self.path)
                self._mtime = current
                self.dirty.set()
                LOG.info("Reloaded %s after an external edit", self.path)
            except ValueError as err:
                LOG.warning("Ignoring unreadable %s: %s", self.path, err)

    def _trip(self, trip_id=None):
        trip_id = trip_id or self._data.get("active_trip")
        for trip in self._data.get("trips") or []:
            if trip["id"] == trip_id:
                return trip
        raise TripNotFound(trip_id or "(no trip)")

    @property
    def catalog(self):
        return self._data.get("items") or []

    # -- reads -------------------------------------------------------------

    @guarded
    def state(self, trip_id=None):
        trips = [
            {
                "id": t["id"],
                "name": t["name"],
                "start": t.get("start"),
                "end": t.get("end"),
                "days": len(t.get("days") or []),
                "progress": model.progress(t),
            }
            for t in self._data.get("trips") or []
        ]
        try:
            trip = self._trip(trip_id)
        except TripNotFound:
            if trip_id:
                raise  # an explicit trip id that does not exist is a 404
            return {
                "active_trip": None,
                "trips": trips,
                "catalog": self.catalog,
                "categories": self.categories(),
                "tags": self.tags(),
            }
        return {
            "active_trip": {
                "id": trip["id"],
                "name": trip["name"],
                "start": trip.get("start"),
                "end": trip.get("end"),
                "notes": trip.get("notes"),
                "progress": model.progress(trip),
                "packing": model.packing_view(self.catalog, trip),
                "days": model.day_view(self.catalog, trip),
                "dismissed": trip.get("dismissed") or [],
                "waiting": len(model.itinerary_candidates(self.catalog, trip))
                + len(model.essential_candidates(self.catalog, trip)),
            },
            "trips": trips,
            "catalog": self.catalog,
            "categories": self.categories(),
            "tags": self.tags(),
        }

    def categories(self):
        seen = []
        for item in self.catalog:
            cat = item.get("category") or "other"
            if cat not in seen:
                seen.append(cat)
        return sorted(seen)

    def tags(self):
        seen = set()
        for item in self.catalog:
            seen.update(model.tags_of(item))
        for trip in self._data.get("trips") or []:
            seen.update(model.trip_tags(trip))
        return sorted(seen)

    @guarded
    def summary(self, trip_id=None):
        return model.summary(self.catalog, self._trip(trip_id))

    def suggestion_cards(self, item_ids, trip):
        """Turn suggested ids into what the UI shows in the 'bring these too?' tray."""
        by_id = model.index_items(self.catalog)
        cards = []
        for item_id in item_ids:
            item = by_id.get(item_id)
            if not item:
                continue
            cards.append(
                {
                    "item_id": item_id,
                    "name": item.get("name"),
                    "category": item.get("category"),
                    "notes": item.get("notes") or "",
                    "further": len(model.suggestions_for(self.catalog, trip, item_id)),
                }
            )
        return cards

    # -- packing list ------------------------------------------------------

    @guarded
    def add(self, item_id, trip_id=None, reason=None):
        trip = self._trip(trip_id)
        if item_id not in model.index_items(self.catalog):
            raise ItemNotFound(item_id)
        _, created = model.add_item(trip, item_id, reason or {"kind": "manual"})
        suggestions = model.suggestions_for(self.catalog, trip, item_id)
        self._save()
        return {
            "added": created,
            "item_id": item_id,
            "suggestions": self.suggestion_cards(suggestions, trip),
        }

    @guarded
    def set_state(self, item_id, state, trip_id=None):
        trip = self._trip(trip_id)
        entry = model.set_state(trip, item_id, state)
        if entry is None:
            raise ItemNotFound(item_id)
        self._save()
        return entry

    @guarded
    def toggle(self, item_id, trip_id=None):
        trip = self._trip(trip_id)
        entry = model.toggle_packed(trip, item_id)
        if entry is None:
            raise ItemNotFound(item_id)
        self._save()
        return entry

    @guarded
    def set_qty(self, item_id, qty, trip_id=None):
        """Pin how many to bring, or pass a falsy qty to go back to automatic."""
        trip = self._trip(trip_id)
        entry = model.entry_for(trip, item_id)
        if entry is None:
            raise ItemNotFound(item_id)
        entry["qty"] = max(int(qty), 1) if qty else None
        self._save()
        return entry

    @guarded
    def remove(self, item_id, trip_id=None):
        trip = self._trip(trip_id)
        model.remove_item(trip, item_id)
        self._save()
        return True

    @guarded
    def dismiss(self, item_id, trip_id=None):
        trip = self._trip(trip_id)
        model.dismiss(trip, item_id)
        self._save()
        return True

    @guarded
    def undismiss(self, item_id, trip_id=None):
        trip = self._trip(trip_id)
        model.undismiss(trip, item_id)
        self._save()
        return True

    # -- itinerary-driven adds --------------------------------------------

    @guarded
    def candidates(self, trip_id=None, date=None):
        """What the itinerary (and the essentials flag) would like to add."""
        trip = self._trip(trip_id)
        by_id = model.index_items(self.catalog)
        days_by_date = {d["date"]: d for d in trip.get("days") or []}
        cards = []
        for item_id, reasons in model.itinerary_candidates(
            self.catalog, trip, date
        ).items():
            item = by_id.get(item_id, {})
            cards.append(
                {
                    "item_id": item_id,
                    "name": item.get("name"),
                    "category": item.get("category"),
                    "notes": item.get("notes") or "",
                    "why": [
                        model.reason_text(r, by_id, days_by_date) for r in reasons
                    ],
                    "reasons": reasons,
                }
            )
        if date is None:
            for item_id in model.essential_candidates(self.catalog, trip):
                item = by_id.get(item_id, {})
                cards.append(
                    {
                        "item_id": item_id,
                        "name": item.get("name"),
                        "category": item.get("category"),
                        "notes": item.get("notes") or "",
                        "why": ["Always packed"],
                        "reasons": [{"kind": "essential"}],
                    }
                )
        cards.sort(key=lambda c: ((c.get("category") or ""), c.get("name") or ""))
        return cards

    @guarded
    def pull(self, trip_id=None, date=None, include_essentials=True):
        """Accept every pending candidate at once."""
        trip = self._trip(trip_id)
        candidates = model.itinerary_candidates(self.catalog, trip, date)
        if include_essentials and date is None:
            for item_id in model.essential_candidates(self.catalog, trip):
                candidates.setdefault(item_id, []).append({"kind": "essential"})
        added = model.apply_candidates(trip, candidates)
        self._save()
        return {"added": added, "count": len(added)}

    # -- catalog CRUD ------------------------------------------------------

    @guarded
    def save_item(self, raw):
        taken = {i["id"] for i in self.catalog}
        item = store.normalize_item(raw, taken)
        items = self.catalog
        for index, existing in enumerate(items):
            if existing["id"] == item["id"]:
                items[index] = item
                break
        else:
            items.append(item)
        self._data["items"] = items
        self._save()
        return item

    @guarded
    def delete_item(self, item_id):
        self._data["items"] = [i for i in self.catalog if i["id"] != item_id]
        for item in self._data["items"]:
            item["suggests"] = [s for s in item.get("suggests") or [] if s != item_id]
        for trip in self._data.get("trips") or []:
            model.remove_item(trip, item_id)
        self._save()
        return True

    # -- trip CRUD ---------------------------------------------------------

    @guarded
    def save_trip(self, raw):
        taken = {t["id"] for t in self._data.get("trips") or []}
        incoming = store.normalize_trip(raw, taken)
        trips = self._data.setdefault("trips", [])
        for index, existing in enumerate(trips):
            if existing["id"] == incoming["id"]:
                # Editing a trip never wipes what is already packed.
                incoming["packing"] = incoming["packing"] or existing.get("packing", [])
                incoming["dismissed"] = (
                    incoming["dismissed"] or existing.get("dismissed", [])
                )
                trips[index] = incoming
                break
        else:
            trips.append(incoming)
        if not self._data.get("active_trip"):
            self._data["active_trip"] = incoming["id"]
        self._save()
        return incoming

    @guarded
    def save_day(self, trip_id, raw):
        trip = self._trip(trip_id)
        day = store.normalize_day(raw)
        days = trip.setdefault("days", [])
        for index, existing in enumerate(days):
            if existing["date"] == day["date"]:
                days[index] = day
                break
        else:
            days.append(day)
        days.sort(key=lambda d: d["date"])
        self._save()
        return day

    @guarded
    def delete_day(self, trip_id, date):
        trip = self._trip(trip_id)
        trip["days"] = [d for d in trip.get("days") or [] if d["date"] != date]
        self._save()
        return True

    @guarded
    def delete_trip(self, trip_id):
        self._data["trips"] = [
            t for t in self._data.get("trips") or [] if t["id"] != trip_id
        ]
        if self._data.get("active_trip") == trip_id:
            trips = self._data["trips"]
            self._data["active_trip"] = trips[0]["id"] if trips else ""
        self._save()
        return True

    @guarded
    def set_active(self, trip_id):
        self._trip(trip_id)
        self._data["active_trip"] = trip_id
        self._save()
        return trip_id

    @guarded
    def reset_trip(self, trip_id=None):
        """Unpack everything — for reusing a trip as a template next time."""
        trip = self._trip(trip_id)
        for entry in trip.get("packing") or []:
            entry["state"] = "todo"
        self._save()
        return True
