"""Reading, validating and writing Stash's data file.

Everything lives in one user-visible file (default /config/stash.json) so it
can be read and edited by hand, backed up, or kept in git.

Reading is lenient on purpose: a hand edit with a typo in a place id must not
lose data on the next save, so unknown references are kept and shown as
missing in the UI. Writes through the API are strict — see controller.py.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import tempfile
from datetime import datetime

from .model import KINDS

SCHEMA_VERSION = 1

DEFAULT_PATH = "/config/stash.json"
SEED_PATH = os.path.join(os.path.dirname(__file__), "seed", "default.json")

MAX_COLS = 60
MAX_ROWS = 20


class ValidationError(ValueError):
    pass


def slugify(value, fallback="item"):
    folded = (value or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", folded).strip("_")
    return slug or fallback


def unique_id(base, taken, fallback="item"):
    slug = slugify(base, fallback)
    if slug not in taken:
        return slug
    n = 2
    while "%s_%d" % (slug, n) in taken:
        n += 1
    return "%s_%d" % (slug, n)


def new_location_id():
    return "loc_" + secrets.token_hex(4)


# --------------------------------------------------------------------------
# small parsers
# --------------------------------------------------------------------------

def _int(value, low, high, default):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def parse_cell(value):
    """{"col": 14, "row": 2}, [14, 2] or "14,2" → {"col": 14, "row": 2} or None."""
    if value in (None, "", [], {}):
        return None
    if isinstance(value, str):
        value = [part for part in re.split(r"[,\s]+", value.strip()) if part]
    if isinstance(value, (list, tuple)):
        if len(value) != 2:
            raise ValidationError("a compartment needs a column and a row")
        value = {"col": value[0], "row": value[1]}
    if not isinstance(value, dict):
        raise ValidationError("a compartment needs a column and a row")
    try:
        col, row = int(value.get("col")), int(value.get("row"))
    except (TypeError, ValueError):
        raise ValidationError("column and row must be whole numbers")
    if col < 1 or row < 1:
        raise ValidationError("columns and rows count from 1")
    return {"col": col, "row": row}


def parse_qty(value):
    """A count, or None for "some, not counted"."""
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationError("quantity must be a whole number")
    if number < 0:
        raise ValidationError("quantity cannot be negative")
    return number


def _clean_tags(value):
    if isinstance(value, str):
        value = value.split(",")
    return sorted({str(t).strip().lower() for t in (value or []) if str(t).strip()})


def _text(value):
    return str(value or "").strip()


# --------------------------------------------------------------------------
# normalisation
# --------------------------------------------------------------------------

def normalize_place(raw, taken_ids=()):
    if not isinstance(raw, dict):
        raise ValidationError("place must be an object")
    name = _text(raw.get("name"))
    if not name:
        raise ValidationError("place needs a name")
    kind = _text(raw.get("kind")).lower() or "area"
    if kind not in KINDS:
        raise ValidationError("kind must be one of %s" % ", ".join(KINDS))
    place_id = _text(raw.get("id")) or unique_id(name, set(taken_ids), "place")
    try:
        cell = parse_cell(raw.get("cell"))
    except ValidationError:
        cell = None
    place = {
        "id": slugify(place_id, "place"),
        "name": name,
        "kind": kind,
        "parent": slugify(_text(raw.get("parent"))) if _text(raw.get("parent")) else None,
        "cell": cell,
        "notes": _text(raw.get("notes")),
    }
    if kind == "grid":
        cols_from = _text(raw.get("count_cols_from")).lower()
        rows_from = _text(raw.get("count_rows_from")).lower()
        place.update(
            {
                "cols": _int(raw.get("cols"), 1, MAX_COLS, 4),
                "rows": _int(raw.get("rows"), 1, MAX_ROWS, 4),
                "count_cols_from": cols_from if cols_from in ("left", "right") else "left",
                "count_rows_from": rows_from if rows_from in ("top", "bottom") else "top",
            }
        )
    return place


def normalize_location(raw):
    if not isinstance(raw, dict):
        raise ValidationError("location must be an object")
    place = _text(raw.get("place"))
    if not place:
        raise ValidationError("location needs a place")
    try:
        cell = parse_cell(raw.get("cell"))
    except ValidationError:
        cell = None
    try:
        qty = parse_qty(raw.get("qty"))
    except ValidationError:
        qty = None
    return {
        "id": _text(raw.get("id")) or new_location_id(),
        "place": slugify(place, "place"),
        "cell": cell,
        "qty": qty,
        "note": _text(raw.get("note")),
    }


def normalize_item(raw, taken_ids=()):
    if not isinstance(raw, dict):
        raise ValidationError("item must be an object")
    name = _text(raw.get("name"))
    if not name:
        raise ValidationError("item needs a name")
    item_id = _text(raw.get("id")) or unique_id(name, set(taken_ids))
    locations, seen = [], set()
    for raw_loc in raw.get("locations") or []:
        try:
            loc = normalize_location(raw_loc)
        except ValidationError:
            continue
        while loc["id"] in seen:
            loc["id"] = new_location_id()
        seen.add(loc["id"])
        locations.append(loc)
    return {
        "id": slugify(item_id),
        "name": name,
        "category": _text(raw.get("category")),
        "tags": _clean_tags(raw.get("tags")),
        "notes": _text(raw.get("notes")),
        "locations": locations,
    }


def _break_loops(places):
    """A parent chain that comes back on itself is cut where it closes."""
    by_id = {p["id"]: p for p in places}
    for place in places:
        seen = {place["id"]}
        current = by_id.get(place.get("parent"))
        while current is not None:
            if current["id"] in seen:
                place["parent"] = None
                break
            seen.add(current["id"])
            current = by_id.get(current.get("parent"))


def normalize_data(raw):
    if not isinstance(raw, dict):
        raise ValidationError("data file must be a JSON object")
    places, place_ids = [], set()
    for raw_place in raw.get("places") or []:
        place = normalize_place(raw_place, place_ids)
        if place["id"] in place_ids:
            continue
        place_ids.add(place["id"])
        places.append(place)
    _break_loops(places)
    items, item_ids = [], set()
    for raw_item in raw.get("items") or []:
        item = normalize_item(raw_item, item_ids)
        if item["id"] in item_ids:
            continue
        item_ids.add(item["id"])
        items.append(item)
    return {"version": SCHEMA_VERSION, "places": places, "items": items}


# --------------------------------------------------------------------------
# disk
# --------------------------------------------------------------------------

def empty_data():
    return {"version": SCHEMA_VERSION, "places": [], "items": []}


def read(path=DEFAULT_PATH):
    with open(path, "r", encoding="utf-8") as handle:
        return normalize_data(json.load(handle))


def write(data, path=DEFAULT_PATH):
    """Atomic write: replace the file in one step or not at all."""
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=folder, prefix=".stash-", suffix=".tmp", delete=False
    )
    try:
        with handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
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
