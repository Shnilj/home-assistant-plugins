"""Pure logic for Stash: where things are, how to say it, how to find them.

Nothing in here touches the disk or the network, so all of it is unit-tested
directly. The shapes it works on are the normalised ones from store.py:

    place    {id, name, kind, parent, cell, notes, cols, rows,
              count_cols_from, count_rows_from}
    item     {id, name, category, tags, notes, locations: [location]}
    location {id, place, cell, qty, note}

A *cell* is {"col": c, "row": r}, 1-based, counted the way that wall says it
is counted ("14th from the right, 2nd from the top" is col 14, row 2 on a wall
whose columns count from the right). Storing the wall's own numbers keeps the
JSON file readable by the person who has to stand in front of the shelf.
"""

from __future__ import annotations

import re
import unicodedata

KINDS = ("room", "grid", "area", "container")
KIND_LABELS = {
    "room": "Room",
    "grid": "Shelf wall",
    "area": "Area",
    "container": "Box",
}
SEPARATOR = " › "


# --------------------------------------------------------------------------
# words
# --------------------------------------------------------------------------

def ordinal(n):
    n = int(n)
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "%d%s" % (n, suffix)


def cell_label(grid, cell, short=False):
    """'14th from the right, 2nd from the top' — or '14 · 2' when short."""
    if not cell:
        return ""
    col, row = cell.get("col"), cell.get("row")
    if short:
        return "%s · %s" % (col, row)
    cols_from = (grid or {}).get("count_cols_from") or "left"
    rows_from = (grid or {}).get("count_rows_from") or "top"
    parts = []
    if col:
        parts.append("%s from the %s" % (ordinal(col), cols_from))
    if row:
        parts.append("%s from the %s" % (ordinal(row), rows_from))
    return ", ".join(parts)


def cell_key(cell):
    return "%s,%s" % (cell.get("col"), cell.get("row")) if cell else ""


def merge_location(locations, loc):
    """Add a location, or fold it into one already at the same spot.

    Counts add up; if either side is "not counted" the merged one stays not
    counted. Returns the location that now holds it.
    """
    for other in locations:
        if other is loc:
            continue
        if other["place"] == loc["place"] and same_cell(other.get("cell"), loc.get("cell")):
            if other.get("qty") is not None and loc.get("qty") is not None:
                other["qty"] += loc["qty"]
            note = loc.get("note") or ""
            if note and note not in (other.get("note") or ""):
                other["note"] = ((other.get("note") or "") + "; " + note).strip("; ")
            if loc in locations:
                locations.remove(loc)
            return other
    if loc not in locations:
        locations.append(loc)
    return loc


def same_cell(a, b):
    if not a and not b:
        return True
    if not a or not b:
        return False
    return a.get("col") == b.get("col") and a.get("row") == b.get("row")


# --------------------------------------------------------------------------
# geometry of a wall
# --------------------------------------------------------------------------

def physical(grid, cell):
    """The wall's own numbers → (x, y) from the top-left corner, 1-based."""
    cols, rows = int(grid.get("cols") or 1), int(grid.get("rows") or 1)
    col, row = int(cell["col"]), int(cell["row"])
    x = cols - col + 1 if grid.get("count_cols_from") == "right" else col
    y = rows - row + 1 if grid.get("count_rows_from") == "bottom" else row
    return x, y


def from_physical(grid, x, y):
    cols, rows = int(grid.get("cols") or 1), int(grid.get("rows") or 1)
    col = cols - x + 1 if grid.get("count_cols_from") == "right" else x
    row = rows - y + 1 if grid.get("count_rows_from") == "bottom" else y
    return {"col": col, "row": row}


def in_bounds(grid, cell):
    if not cell:
        return True
    try:
        col, row = int(cell["col"]), int(cell["row"])
    except (KeyError, TypeError, ValueError):
        return False
    return 1 <= col <= int(grid.get("cols") or 0) and 1 <= row <= int(grid.get("rows") or 0)


def renumber(old_grid, new_grid, cell):
    """Keep a cell on the same physical spot when a wall's counting changes.

    The wall keeps its anchor corner — the one numbering starts from — so
    widening a wall that counts from the right adds columns on the left, and
    existing numbers stay put. Only a change of *direction* moves numbers.
    """
    if not cell:
        return cell
    col, row = int(cell["col"]), int(cell["row"])
    if (old_grid.get("count_cols_from") or "left") != (new_grid.get("count_cols_from") or "left"):
        col = int(new_grid.get("cols") or 1) - col + 1
    if (old_grid.get("count_rows_from") or "top") != (new_grid.get("count_rows_from") or "top"):
        row = int(new_grid.get("rows") or 1) - row + 1
    return {"col": col, "row": row}


# --------------------------------------------------------------------------
# the tree
# --------------------------------------------------------------------------

def index(rows):
    return {row["id"]: row for row in rows or []}


def ancestors(by_id, place_id):
    """[root, ..., place] — stops on a missing parent or a loop."""
    chain, seen = [], set()
    current = by_id.get(place_id)
    while current is not None and current["id"] not in seen:
        seen.add(current["id"])
        chain.append(current)
        current = by_id.get(current.get("parent")) if current.get("parent") else None
    chain.reverse()
    return chain


def descendants(places, place_id):
    """Every place below place_id (not including it)."""
    children = {}
    for place in places or []:
        children.setdefault(place.get("parent"), []).append(place["id"])
    out, stack = set(), list(children.get(place_id, []))
    while stack:
        current = stack.pop()
        if current in out or current == place_id:
            continue
        out.add(current)
        stack.extend(children.get(current, []))
    return out


def path(by_id, place_id, cell=None):
    """Segments from the room down to the exact spot.

    Each segment is {"kind": ..., "label": ..., "id": place id or None}. A cell
    becomes its own segment, right after the wall it belongs to, so
    "Left Kallax › 14th from the right, 2nd from the top › Black box" reads in
    the order you would walk to it.
    """
    segments = []
    chain = ancestors(by_id, place_id)
    if not chain and place_id:
        return [{"kind": "missing", "label": "Unknown place '%s'" % place_id, "id": place_id}]
    for node in chain:
        if node.get("cell"):
            parent = by_id.get(node.get("parent"))
            if parent and parent.get("kind") == "grid":
                segments.append(_cell_segment(parent, node["cell"]))
        segments.append({"kind": node.get("kind"), "label": node["name"], "id": node["id"]})
    if cell:
        place = by_id.get(place_id)
        if place and place.get("kind") == "grid":
            segments.append(_cell_segment(place, cell))
    return segments


def _cell_segment(grid, cell):
    return {
        "kind": "cell",
        "label": cell_label(grid, cell),
        "short": cell_label(grid, cell, short=True),
        "id": grid["id"],
        "cell": {"col": cell["col"], "row": cell["row"]},
    }


def path_text(segments):
    return SEPARATOR.join(s["label"] for s in segments)


# --------------------------------------------------------------------------
# what is where
# --------------------------------------------------------------------------

def locations_at(items, place_id, cell=None, any_cell=False):
    """(item, location) pairs placed directly at place_id (and cell)."""
    out = []
    for item in items or []:
        for loc in item.get("locations") or []:
            if loc.get("place") != place_id:
                continue
            if not any_cell and not same_cell(loc.get("cell"), cell):
                continue
            out.append((item, loc))
    return out


def children_of(places, place_id, cell=None, any_cell=False):
    out = []
    for place in places or []:
        if place.get("parent") != place_id:
            continue
        if not any_cell and not same_cell(place.get("cell"), cell):
            continue
        out.append(place)
    return sorted(out, key=lambda p: (p["kind"] != "container", p["name"].lower()))


def count_inside(places, items, place_id):
    """How many item-locations sit in this place or anywhere below it."""
    scope = descendants(places, place_id) | {place_id}
    return sum(
        1
        for item in items or []
        for loc in item.get("locations") or []
        if loc.get("place") in scope
    )


def grid_map(places, items, grid):
    """Per-cell summary for drawing a wall: what is in each compartment."""
    cells = {}

    def bucket(cell):
        key = cell_key(cell)
        if key not in cells:
            cells[key] = {"cell": dict(cell), "items": 0, "containers": [], "names": []}
        return cells[key]

    for item, loc in locations_at(items, grid["id"], any_cell=True):
        if loc.get("cell"):
            entry = bucket(loc["cell"])
            entry["items"] += 1
            entry["names"].append(item["name"])
    for child in children_of(places, grid["id"], any_cell=True):
        if not child.get("cell"):
            continue
        entry = bucket(child["cell"])
        inside = count_inside(places, items, child["id"])
        entry["items"] += inside
        entry["containers"].append({"id": child["id"], "name": child["name"], "items": inside})
    for entry in cells.values():
        entry["names"] = sorted(set(entry["names"]), key=str.lower)
    return cells


# --------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------

def fold(text):
    """Lower-case, accents off: 'Câble' finds 'cable'."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def compact(text):
    """Punctuation and spaces off: 'usbc' finds 'USB-C', 'usb c' too."""
    return re.sub(r"[^a-z0-9]+", "", fold(text))


def tokens(query):
    return [t for t in re.split(r"\s+", fold(query).strip()) if t]


def _matches(token, hay, hay_compact):
    if token in hay:
        return True
    squeezed = compact(token)
    return bool(squeezed) and squeezed in hay_compact


def item_haystack(item):
    return " ".join(
        [item.get("name") or "", item.get("category") or "", item.get("notes") or ""]
        + list(item.get("tags") or [])
        + [loc.get("note") or "" for loc in item.get("locations") or []]
    )


def search(places, items, query, limit=50):
    """Items (and places) matching every word of the query.

    Ranking: a name that starts with the query beats a name that contains it,
    which beats a hit only in tags, category or notes. Ties go alphabetical.
    """
    words = tokens(query)
    if not words:
        return {"items": [], "places": []}
    phrase = fold(query).strip()

    scored = []
    for item in items or []:
        hay = fold(item_haystack(item))
        hay_compact = compact(hay)
        if not all(_matches(w, hay, hay_compact) for w in words):
            continue
        name = fold(item.get("name"))
        name_compact = compact(name)
        if name.startswith(phrase) or name_compact.startswith(compact(phrase)):
            score = 0
        elif all(_matches(w, name, name_compact) for w in words):
            score = 1
        else:
            score = 2
        scored.append((score, name, item))
    scored.sort(key=lambda row: (row[0], row[1]))

    found_places = []
    for place in places or []:
        hay = fold("%s %s" % (place.get("name"), place.get("notes") or ""))
        if all(_matches(w, hay, compact(hay)) for w in words):
            found_places.append(place)
    found_places.sort(key=lambda p: fold(p["name"]))

    return {
        "items": [row[2] for row in scored[:limit]],
        "places": found_places[:limit],
    }


# --------------------------------------------------------------------------
# views the UI draws from
# --------------------------------------------------------------------------

def location_view(by_id, loc):
    segments = path(by_id, loc.get("place"), loc.get("cell"))
    return {
        "id": loc["id"],
        "place": loc.get("place"),
        "cell": loc.get("cell"),
        "qty": loc.get("qty"),
        "note": loc.get("note") or "",
        "path": segments,
        "text": path_text(segments),
        "missing": any(s["kind"] == "missing" for s in segments),
    }


def item_view(by_id, item):
    locations = [location_view(by_id, loc) for loc in item.get("locations") or []]
    locations.sort(key=lambda loc: loc["text"].lower())
    counted = [loc["qty"] for loc in locations if loc["qty"] is not None]
    return {
        "id": item["id"],
        "name": item["name"],
        "category": item.get("category") or "",
        "tags": item.get("tags") or [],
        "notes": item.get("notes") or "",
        "locations": locations,
        "total": sum(counted) if counted else None,
        "uncounted": len(locations) - len(counted),
    }


def place_view(places, items, place_id, cell=None):
    """Everything needed to show one place, or one compartment of a wall."""
    by_id = index(places)
    place = by_id[place_id]
    is_grid = place.get("kind") == "grid"
    # On a wall with no cell chosen, list what hangs on the wall as a whole.
    here = locations_at(items, place_id, cell)
    kids = children_of(places, place_id, cell)
    view = {
        "place": place_summary(places, items, place),
        "cell": cell,
        "cell_label": cell_label(place, cell) if cell else "",
        "path": path(by_id, place_id, cell),
        "children": [place_summary(places, items, child, by_id) for child in kids],
        "items": [
            {
                "item_id": item["id"],
                "name": item["name"],
                "category": item.get("category") or "",
                "location_id": loc["id"],
                "qty": loc.get("qty"),
                "note": loc.get("note") or "",
                "elsewhere": len(item.get("locations") or []) - 1,
            }
            for item, loc in sorted(here, key=lambda pair: fold(pair[0]["name"]))
        ],
    }
    if is_grid and not cell:
        view["grid"] = {
            "cols": place.get("cols"),
            "rows": place.get("rows"),
            "count_cols_from": place.get("count_cols_from"),
            "count_rows_from": place.get("count_rows_from"),
            "cells": grid_map(places, items, place),
        }
    return view


def place_summary(places, items, place, by_id=None):
    by_id = by_id or index(places)
    out = {
        "id": place["id"],
        "name": place["name"],
        "kind": place.get("kind"),
        "kind_label": KIND_LABELS.get(place.get("kind"), "Place"),
        "parent": place.get("parent"),
        "cell": place.get("cell"),
        "notes": place.get("notes") or "",
        "count": count_inside(places, items, place["id"]),
        "children": len([p for p in places if p.get("parent") == place["id"]]),
    }
    if place.get("cell"):
        parent = by_id.get(place.get("parent"))
        if parent and parent.get("kind") == "grid":
            out["cell_label"] = cell_label(parent, place["cell"])
            out["cell_short"] = cell_label(parent, place["cell"], short=True)
    if place.get("kind") == "grid":
        for key in ("cols", "rows", "count_cols_from", "count_rows_from"):
            out[key] = place.get(key)
    return out
