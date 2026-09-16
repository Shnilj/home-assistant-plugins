"""Reading, validating and writing TripPack's data file.

Everything lives in one user-visible file (default /config/trippack.json) so
it can be edited by hand, backed up, or kept in git alongside the itinerary.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import datetime

SCHEMA_VERSION = 1

DEFAULT_PATH = "/config/trippack.json"
SEED_PATH = os.path.join(os.path.dirname(__file__), "seed", "default.json")


class ValidationError(ValueError):
    pass


def slugify(value, fallback="item"):
    slug = re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")
    return slug or fallback


def unique_id(base, taken):
    slug = slugify(base)
    if slug not in taken:
        return slug
    n = 2
    while "%s_%d" % (slug, n) in taken:
        n += 1
    return "%s_%d" % (slug, n)


# --------------------------------------------------------------------------
# validation / normalisation
# --------------------------------------------------------------------------

def _clean_tags(value):
    if isinstance(value, str):
        value = value.split(",")
    return sorted({str(t).strip().lower() for t in (value or []) if str(t).strip()})


def normalize_item(raw, taken_ids=()):
    if not isinstance(raw, dict):
        raise ValidationError("item must be an object")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValidationError("item needs a name")
    item_id = str(raw.get("id") or "").strip() or unique_id(name, set(taken_ids))
    return {
        "id": slugify(item_id),
        "name": name,
        "category": str(raw.get("category") or "other").strip() or "other",
        "tags": _clean_tags(raw.get("tags")),
        "suggests": [slugify(s) for s in (raw.get("suggests") or []) if str(s).strip()],
        "always": bool(raw.get("always")),
        "qty": raw.get("qty") or None,
        "notes": str(raw.get("notes") or "").strip(),
    }


def normalize_day(raw):
    date = str(raw.get("date") or "").strip()
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise ValidationError("day needs a date as YYYY-MM-DD, got %r" % (date,))
    return {
        "date": date,
        "title": str(raw.get("title") or "").strip(),
        "tags": _clean_tags(raw.get("tags")),
        "notes": str(raw.get("notes") or "").strip(),
    }


def normalize_trip(raw, taken_ids=()):
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValidationError("trip needs a name")
    trip_id = str(raw.get("id") or "").strip() or unique_id(name, set(taken_ids))
    days = sorted(
        (normalize_day(d) for d in raw.get("days") or []), key=lambda d: d["date"]
    )
    packing = []
    for entry in raw.get("packing") or []:
        item_id = slugify(str(entry.get("item_id") or ""))
        if not item_id:
            continue
        state = entry.get("state") or "todo"
        packing.append(
            {
                "item_id": item_id,
                "state": state if state in ("todo", "packed", "skipped") else "todo",
                "qty": entry.get("qty") or None,
                "reasons": [r for r in entry.get("reasons") or [] if isinstance(r, dict)],
                "added_at": entry.get("added_at")
                or datetime.now().isoformat(timespec="seconds"),
            }
        )
    return {
        "id": slugify(trip_id, "trip"),
        "name": name,
        "start": str(raw.get("start") or (days[0]["date"] if days else "")).strip(),
        "end": str(raw.get("end") or (days[-1]["date"] if days else "")).strip(),
        "notes": str(raw.get("notes") or "").strip(),
        "days": days,
        "packing": packing,
        "dismissed": [slugify(i) for i in raw.get("dismissed") or []],
    }


def normalize_data(raw):
    if not isinstance(raw, dict):
        raise ValidationError("data file must be a JSON object")
    items, seen = [], set()
    for raw_item in raw.get("items") or []:
        item = normalize_item(raw_item, seen)
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        items.append(item)
    trips, trip_ids = [], set()
    for raw_trip in raw.get("trips") or []:
        trip = normalize_trip(raw_trip, trip_ids)
        if trip["id"] in trip_ids:
            continue
        trip_ids.add(trip["id"])
        trips.append(trip)
    active = str(raw.get("active_trip") or "").strip()
    if active not in trip_ids:
        active = trips[0]["id"] if trips else ""
    return {
        "version": SCHEMA_VERSION,
        "active_trip": active,
        "items": items,
        "trips": trips,
    }


def dangling_suggestions(data):
    """Suggestion links pointing at items that no longer exist."""
    known = {item["id"] for item in data.get("items") or []}
    out = {}
    for item in data.get("items") or []:
        missing = [s for s in item.get("suggests") or [] if s not in known]
        if missing:
            out[item["id"]] = missing
    return out


# --------------------------------------------------------------------------
# disk
# --------------------------------------------------------------------------

def empty_data():
    return {"version": SCHEMA_VERSION, "active_trip": "", "items": [], "trips": []}


def read(path=DEFAULT_PATH):
    with open(path, "r", encoding="utf-8") as handle:
        return normalize_data(json.load(handle))


def write(data, path=DEFAULT_PATH):
    """Atomic write — a half-written packing list the night before is no fun."""
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=folder, prefix=".trippack-", suffix=".tmp", delete=False
    )
    try:
        with handle:
            json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except Exception:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise
    return path


def load_or_seed(path=DEFAULT_PATH, seed_path=SEED_PATH, seed=True):
    """Read the data file, creating it from the bundled seed on first run."""
    if os.path.exists(path):
        try:
            return read(path)
        except (ValueError, OSError) as err:
            backup = "%s.broken-%s" % (path, datetime.now().strftime("%Y%m%d%H%M%S"))
            try:
                shutil.copy2(path, backup)
            except OSError:
                backup = "(no backup)"
            raise ValidationError(
                "%s could not be read (%s). A copy was kept at %s." % (path, err, backup)
            )
    data = empty_data()
    if seed and seed_path and os.path.exists(seed_path):
        with open(seed_path, "r", encoding="utf-8") as handle:
            data = normalize_data(json.load(handle))
    write(data, path)
    return data


def mtime(path=DEFAULT_PATH):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0
