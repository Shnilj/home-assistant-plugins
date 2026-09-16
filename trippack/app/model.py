"""Pure packing logic for TripPack.

No IO, no Flask, no MQTT — everything here is a plain function over plain
dicts so it can be unit-tested without a Supervisor, a broker or a disk.

Data shapes
-----------
item    {id, name, category, tags[], suggests[], always, qty, per_day,
         qty_max, notes}
day     {date, title, tags[], notes}
entry   {item_id, state, qty, reasons[], added_at}   qty None = automatic
reason  {kind: manual|essential|suggested_by|day, ...}
trip    {id, name, start, end, days[], packing[], dismissed[]}
"""

from __future__ import annotations

import math
from datetime import datetime

STATES = ("todo", "packed", "skipped")

# A suggestion chain longer than this is almost certainly a data mistake.
MAX_CHAIN = 6


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

def index_items(catalog):
    """{item_id: item} for a catalog list."""
    return {item["id"]: item for item in catalog}


def tags_of(obj):
    return [str(t).strip().lower() for t in (obj.get("tags") or []) if str(t).strip()]


def entry_for(trip, item_id):
    for entry in trip.get("packing") or []:
        if entry.get("item_id") == item_id:
            return entry
    return None


def on_list(trip, item_id):
    return entry_for(trip, item_id) is not None


def is_dismissed(trip, item_id):
    return item_id in (trip.get("dismissed") or [])


def trip_tags(trip):
    """Every tag used anywhere in the itinerary, in first-seen order."""
    seen = []
    for day in trip.get("days") or []:
        for tag in tags_of(day):
            if tag not in seen:
                seen.append(tag)
    return seen


# --------------------------------------------------------------------------
# how many to bring
# --------------------------------------------------------------------------

def trip_length(trip):
    """Days the trip runs. The itinerary decides; the dates are the fallback."""
    days = trip.get("days") or []
    if days:
        return len(days)
    try:
        first = datetime.strptime(trip.get("start"), "%Y-%m-%d")
        last = datetime.strptime(trip.get("end"), "%Y-%m-%d")
        return max((last - first).days + 1, 1)
    except (TypeError, ValueError):
        return 1


def suggested_qty(item, days):
    """What an item works out at for a trip of `days` days.

    `per_day` scales with the trip, `qty_max` is the point where you do
    laundry instead of packing more, and a plain `qty` is a fixed number.
    None means the item is not counted at all — one toothbrush is one
    toothbrush however long you are away.
    """
    per_day = item.get("per_day")
    if per_day:
        count = int(math.ceil(float(per_day) * max(int(days), 1)))
    elif item.get("qty"):
        count = int(item["qty"])
    else:
        return None
    ceiling = item.get("qty_max")
    if ceiling:
        count = min(count, int(ceiling))
    return max(count, 1)


def entry_qty(item, trip, entry):
    """(how many, pinned). A number on the entry beats the computed one."""
    chosen = (entry or {}).get("qty")
    if chosen:
        return int(chosen), True
    return suggested_qty(item or {}, trip_length(trip)), False


# --------------------------------------------------------------------------
# reasons — the "why is this on my list?" trail
# --------------------------------------------------------------------------

def reason_key(reason):
    """Identity of a reason, so the same one is not recorded twice."""
    kind = reason.get("kind")
    if kind == "suggested_by":
        return (kind, reason.get("item_id"))
    if kind == "day":
        return (kind, reason.get("date"), reason.get("tag"))
    return (kind,)


def add_reason(entry, reason):
    """Append a reason unless an identical one is already recorded."""
    if not reason:
        return False
    reasons = entry.setdefault("reasons", [])
    keys = {reason_key(r) for r in reasons}
    if reason_key(reason) in keys:
        return False
    reasons.append(reason)
    return True


def reason_text(reason, items_by_id=None, days_by_date=None):
    """One human-readable line for a reason."""
    items_by_id = items_by_id or {}
    days_by_date = days_by_date or {}
    kind = reason.get("kind")
    if kind == "manual":
        return "You added it"
    if kind == "essential":
        return "Always packed"
    if kind == "suggested_by":
        other = items_by_id.get(reason.get("item_id"), {})
        return "Goes with %s" % (other.get("name") or reason.get("item_id"))
    if kind == "day":
        date = reason.get("date")
        day = days_by_date.get(date, {})
        title = day.get("title")
        where = "%s — %s" % (pretty_date(date), title) if title else pretty_date(date)
        return "%s needs %s" % (where, reason.get("tag"))
    return kind or "Unknown"


def explain(trip, item_id, catalog=None):
    """All reasons for one item, as readable lines."""
    entry = entry_for(trip, item_id)
    if not entry:
        return []
    items_by_id = index_items(catalog or [])
    days_by_date = {d.get("date"): d for d in trip.get("days") or []}
    return [reason_text(r, items_by_id, days_by_date) for r in entry.get("reasons") or []]


def short_date(value):
    """"19 Sep" — the row has no room for the day name."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d %b").lstrip("0")
    except (TypeError, ValueError):
        return ""


def reason_short(reason, items_by_id=None):
    """A few words for the list row, where the full sentence would not fit.

    Empty for a manual add: "you put it there" is not worth a line.
    """
    items_by_id = items_by_id or {}
    kind = reason.get("kind")
    if kind == "essential":
        return "Always"
    if kind == "suggested_by":
        other = items_by_id.get(reason.get("item_id"), {})
        return other.get("name") or reason.get("item_id") or ""
    if kind == "day":
        return short_date(reason.get("date"))
    return ""


def row_hint(reasons, items_by_id=None):
    """The one short reason a row shows, with a count of the rest."""
    reasons = reasons or []
    for reason in reasons:
        hint = reason_short(reason, items_by_id)
        if hint:
            extra = len(reasons) - 1
            return "%s +%d" % (hint, extra) if extra else hint
    return ""


def pretty_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%a %d %b")
    except (TypeError, ValueError):
        return value or "?"


# --------------------------------------------------------------------------
# mutations
# --------------------------------------------------------------------------

def add_item(trip, item_id, reason=None, qty=None):
    """Put an item on the list, or record another reason for it.

    Returns (entry, created). Adding something that is already there never
    duplicates it — it just deepens the trail.
    """
    entry = entry_for(trip, item_id)
    created = False
    if entry is None:
        entry = {
            "item_id": item_id,
            "state": "todo",
            "qty": qty,
            "reasons": [],
            "added_at": datetime.now().isoformat(timespec="seconds"),
        }
        trip.setdefault("packing", []).append(entry)
        created = True
    elif qty and not entry.get("qty"):
        entry["qty"] = qty
    add_reason(entry, reason or {"kind": "manual"})
    # Adding it back clears an earlier dismissal.
    if is_dismissed(trip, item_id):
        trip["dismissed"] = [i for i in trip["dismissed"] if i != item_id]
    return entry, created


def remove_item(trip, item_id):
    before = len(trip.get("packing") or [])
    trip["packing"] = [e for e in trip.get("packing") or [] if e.get("item_id") != item_id]
    return len(trip["packing"]) != before


def set_state(trip, item_id, state):
    if state not in STATES:
        raise ValueError("unknown state: %r" % (state,))
    entry = entry_for(trip, item_id)
    if entry is None:
        return None
    entry["state"] = state
    return entry


def toggle_packed(trip, item_id):
    entry = entry_for(trip, item_id)
    if entry is None:
        return None
    entry["state"] = "todo" if entry.get("state") == "packed" else "packed"
    return entry


def dismiss(trip, item_id):
    """Not taking it, and stop suggesting it for this trip."""
    remove_item(trip, item_id)
    dismissed = trip.setdefault("dismissed", [])
    if item_id not in dismissed:
        dismissed.append(item_id)
    return True


def undismiss(trip, item_id):
    trip["dismissed"] = [i for i in trip.get("dismissed") or [] if i != item_id]
    return True


# --------------------------------------------------------------------------
# the suggestion graph
# --------------------------------------------------------------------------

def suggestions_for(catalog, trip, item_id, include_dismissed=False):
    """Items that travel with `item_id` and are not on the list yet.

    One level only. The cascade happens naturally: accept a suggestion, the
    accepted item is added, and its own suggestions come back in the reply.
    """
    items_by_id = index_items(catalog)
    item = items_by_id.get(item_id)
    if not item:
        return []
    out = []
    for other_id in item.get("suggests") or []:
        if other_id == item_id or other_id not in items_by_id:
            continue
        if on_list(trip, other_id):
            continue
        if not include_dismissed and is_dismissed(trip, other_id):
            continue
        if other_id not in out:
            out.append(other_id)
    return out


def chain_from(catalog, item_id, _seen=None, _depth=0):
    """Everything reachable through `suggests`, cycle-safe. Used for previews."""
    items_by_id = index_items(catalog)
    _seen = _seen if _seen is not None else set()
    if _depth >= MAX_CHAIN or item_id in _seen:
        return []
    _seen.add(item_id)
    out = []
    for other_id in (items_by_id.get(item_id, {}).get("suggests") or []):
        if other_id in _seen or other_id not in items_by_id:
            continue
        out.append(other_id)
        out.extend(chain_from(catalog, other_id, _seen, _depth + 1))
    return out


# --------------------------------------------------------------------------
# itinerary -> candidate items
# --------------------------------------------------------------------------

def itinerary_candidates(catalog, trip, date=None):
    """{item_id: [reason, ...]} for items whose tags match itinerary days.

    Skips anything already on the list or dismissed. Pass `date` to look at a
    single day.
    """
    days = trip.get("days") or []
    if date:
        days = [d for d in days if d.get("date") == date]
    out = {}
    for day in days:
        day_tags = set(tags_of(day))
        if not day_tags:
            continue
        for item in catalog:
            item_id = item.get("id")
            if on_list(trip, item_id) or is_dismissed(trip, item_id):
                continue
            for tag in tags_of(item):
                if tag in day_tags:
                    out.setdefault(item_id, []).append(
                        {"kind": "day", "date": day.get("date"), "tag": tag}
                    )
    return out


def essential_candidates(catalog, trip):
    """Items flagged `always` that are not on the list yet."""
    return [
        item["id"]
        for item in catalog
        if item.get("always")
        and not on_list(trip, item["id"])
        and not is_dismissed(trip, item["id"])
    ]


def apply_candidates(trip, candidates):
    """Add every candidate with all of its reasons. Returns the new item ids."""
    added = []
    for item_id, reasons in candidates.items():
        _, created = add_item(trip, item_id, reasons[0] if reasons else None)
        for reason in reasons[1:]:
            add_reason(entry_for(trip, item_id), reason)
        if created:
            added.append(item_id)
    return added


# --------------------------------------------------------------------------
# read models for the UI
# --------------------------------------------------------------------------

def progress(trip):
    entries = trip.get("packing") or []
    packed = sum(1 for e in entries if e.get("state") == "packed")
    skipped = sum(1 for e in entries if e.get("state") == "skipped")
    todo = sum(1 for e in entries if e.get("state") == "todo")
    countable = packed + todo
    return {
        "total": len(entries),
        "packed": packed,
        "todo": todo,
        "skipped": skipped,
        "pct": int(round(100.0 * packed / countable)) if countable else 0,
    }


def packing_view(catalog, trip):
    """The list, decorated with item detail and readable reasons."""
    items_by_id = index_items(catalog)
    days_by_date = {d.get("date"): d for d in trip.get("days") or []}
    rows = []
    for entry in trip.get("packing") or []:
        item = items_by_id.get(entry.get("item_id"), {})
        count, pinned = entry_qty(item, trip, entry)
        rows.append(
            {
                "item_id": entry.get("item_id"),
                "name": item.get("name") or entry.get("item_id"),
                "category": item.get("category") or "other",
                "tags": tags_of(item),
                "notes": item.get("notes") or "",
                "state": entry.get("state") or "todo",
                "qty": count,
                "qty_auto": count is not None and not pinned,
                "missing": entry.get("item_id") not in items_by_id,
                "hint": row_hint(entry.get("reasons"), items_by_id),
                "why": [
                    reason_text(r, items_by_id, days_by_date)
                    for r in entry.get("reasons") or []
                ],
            }
        )
    rows.sort(key=lambda r: (r["category"].lower(), r["name"].lower()))
    return rows


def day_view(catalog, trip):
    """Itinerary days with how many matching items are still unpacked."""
    rows = []
    for day in trip.get("days") or []:
        day_tags = set(tags_of(day))
        matching, unpacked = [], 0
        for item in catalog:
            if day_tags & set(tags_of(item)):
                matching.append(item["id"])
                entry = entry_for(trip, item["id"])
                if entry is None or entry.get("state") == "todo":
                    if not is_dismissed(trip, item["id"]):
                        unpacked += 1
        rows.append(
            {
                "date": day.get("date"),
                "label": pretty_date(day.get("date")),
                "title": day.get("title") or "",
                "notes": day.get("notes") or "",
                "tags": sorted(day_tags),
                "matching": len(matching),
                "unpacked": unpacked,
                "candidates": len(itinerary_candidates(catalog, trip, day.get("date"))),
            }
        )
    rows.sort(key=lambda r: r["date"] or "")
    return rows


def summary(catalog, trip):
    """Small dict suitable for a future MQTT publish."""
    prog = progress(trip)
    return {
        "trip": trip.get("name"),
        "trip_id": trip.get("id"),
        "start": trip.get("start"),
        "end": trip.get("end"),
        "packed": prog["packed"],
        "todo": prog["todo"],
        "total": prog["total"],
        "pct": prog["pct"],
        "suggestions_waiting": len(itinerary_candidates(catalog, trip))
        + len(essential_candidates(catalog, trip)),
    }
