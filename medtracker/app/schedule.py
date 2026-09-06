"""MedTracker scheduling engine — pure, side-effect-free, unit-testable.

Given a medication definition and a day, it produces the list of dose instances
due that day, and (with a dose history) works out each instance's status
(upcoming / due / overdue / taken / skipped) and the aggregate view a
medication, subject and the hub expose to Home Assistant.

No IO here: persistence lives in ``store.py`` and orchestration in ``main.py``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

SCHEDULE_TYPES = ("times", "interval")
# A medication's actionable state, most-actionable first.
STATE_ORDER = ("overdue", "due", "upcoming", "done", "none")

# Common fractions rendered as nice glyphs; anything else falls back to a number.
_FRACTIONS = {
    0.125: "⅛",   # 1/8
    0.25: "¼",    # 1/4
    0.333: "⅓",   # 1/3
    0.375: "⅜",   # 3/8
    0.5: "½",     # 1/2
    0.625: "⅝",   # 5/8
    0.667: "⅔",   # 2/3
    0.75: "¾",    # 3/4
    0.875: "⅞",   # 7/8
}


def slugify(name: str) -> str:
    """Turn a name into an entity/topic-safe slug."""
    slug = re.sub(r"[^a-z0-9_]+", "_", str(name).strip().lower())
    return slug.strip("_") or "item"


def parse_hhmm(value: str) -> time:
    """Parse ``"HH:MM"`` into a ``time``. Raises ValueError on bad input."""
    h, m = str(value).strip().split(":")
    h, m = int(h), int(m)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"time out of range: {value}")
    return time(h, m)


def format_dose(amount: float, unit: str = "pill") -> str:
    """Render a dose amount for humans, e.g. ``½ pill``, ``1 pill``, ``2.5 ml``."""
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        amount = 0.0
    unit = (unit or "").strip()
    pluralisable = unit in ("pill", "tablet", "capsule", "drop", "application", "puff", "spray", "unit")
    # Fraction glyphs only make sense for whole-item units (you split a pill, not
    # a millilitre); volume/mass units render as plain decimals.
    fractionable = unit in ("pill", "tablet", "capsule") or unit == ""

    whole = int(amount)
    frac = round(amount - whole, 3)
    # Snap to the nearest known fraction (tolerates 0.333/0.667 rounding).
    glyph = None
    if fractionable:
        for value, sym in _FRACTIONS.items():
            if abs(frac - value) <= 0.02:
                glyph = sym
                break

    if glyph and whole == 0:
        num = glyph
        plural = amount > 1  # a bare fraction < 1 is singular
    elif glyph:
        num = f"{whole}{glyph}"
        plural = True
    else:
        num = f"{amount:g}"
        plural = abs(amount - 1.0) > 1e-9

    if not unit:
        return num
    label = unit
    if plural and pluralisable:
        label = unit + "s"
    return f"{num} {label}"


@dataclass
class DoseInstance:
    key: str          # stable per-day key, e.g. "08:00" (or "08:00#1" if repeated)
    at: datetime      # scheduled datetime (naive local, on the target day)
    dose: float       # amount in the medication's unit


def med_instances(med: dict, day: date) -> list[DoseInstance]:
    """Return the sorted dose instances for ``med`` on ``day``.

    - ``times``: one instance per configured time-of-day, each with its own dose.
    - ``interval``: instances every ``every_hours`` from ``start`` up to ``end``
      (inclusive), all with the same dose. ``end`` before ``start`` is ignored.
    """
    sched = med.get("schedule") or {}
    stype = sched.get("type", "times")
    out: list[DoseInstance] = []

    if stype == "interval":
        try:
            every = float(sched.get("every_hours") or 0)
        except (TypeError, ValueError):
            every = 0
        if every <= 0:
            return []
        try:
            start = parse_hhmm(sched.get("start") or "08:00")
            end = parse_hhmm(sched.get("end") or "22:00")
        except ValueError:
            return []
        try:
            dose = float(sched.get("dose") or 1)
        except (TypeError, ValueError):
            dose = 1.0
        cur = datetime.combine(day, start)
        end_dt = datetime.combine(day, end)
        if end_dt < cur:
            return []
        step = timedelta(hours=every)
        guard = 0
        while cur <= end_dt + timedelta(seconds=1) and guard < 96:
            out.append(DoseInstance(key=cur.strftime("%H:%M"), at=cur, dose=dose))
            cur += step
            guard += 1
    else:  # times
        seen: dict[str, int] = {}
        for entry in sched.get("times") or []:
            try:
                t = parse_hhmm(entry.get("time"))
            except (ValueError, AttributeError):
                continue
            try:
                dose = float(entry.get("dose") or 1)
            except (TypeError, ValueError):
                dose = 1.0
            base = t.strftime("%H:%M")
            n = seen.get(base, 0)
            seen[base] = n + 1
            key = base if n == 0 else f"{base}#{n}"
            out.append(DoseInstance(key=key, at=datetime.combine(day, t), dose=dose))

    out.sort(key=lambda d: d.at)
    return out


def daily_dose_total(med: dict, day: date) -> float:
    """Total dose amount scheduled for a day (used for inventory days-left)."""
    return sum(i.dose for i in med_instances(med, day))


def instance_status(inst: DoseInstance, record: dict | None, now: datetime,
                    lead_min: int, grace_min: int) -> str:
    """Status for one instance: taken / skipped / upcoming / due / overdue."""
    if record:
        st = record.get("status")
        if st in ("taken", "skipped"):
            return st
    lead = timedelta(minutes=max(0, lead_min))
    grace = timedelta(minutes=max(0, grace_min))
    if now < inst.at - lead:
        return "upcoming"
    if now <= inst.at + grace:
        return "due"
    return "overdue"


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone().isoformat() if dt else None


def compute_med(med: dict, med_log: dict, now: datetime, settings) -> dict:
    """Build the full runtime view for a single medication."""
    day = now.date()
    unit = med.get("unit") or "pill"
    insts = med_instances(med, day)

    view_instances = []
    taken = skipped = 0
    due_now = 0
    overdue = False
    last_taken_dt = None
    next_dt = None
    next_dose_label = None

    for inst in insts:
        rec = med_log.get(inst.key)
        status = instance_status(inst, rec, now, settings.upcoming_lead_minutes,
                                 settings.overdue_after_minutes)
        if status == "taken":
            taken += 1
            at = rec.get("at") if rec else None
            try:
                rec_dt = datetime.fromisoformat(at) if at else inst.at
            except ValueError:
                rec_dt = inst.at
            if last_taken_dt is None or rec_dt > last_taken_dt:
                last_taken_dt = rec_dt
        elif status == "skipped":
            skipped += 1
        else:
            if status in ("due", "overdue"):
                due_now += 1
            if status == "overdue":
                overdue = True
            if next_dt is None:
                next_dt = inst.at
                next_dose_label = format_dose(inst.dose, unit)
        view_instances.append({
            "key": inst.key,
            "at": inst.at,
            "at_iso": _iso(inst.at),
            "at_time": inst.at.strftime("%H:%M"),
            "dose": inst.dose,
            "dose_label": format_dose(inst.dose, unit),
            "status": status,
        })

    scheduled = len(insts)
    remaining = scheduled - taken - skipped

    if scheduled == 0:
        state = "none"
    elif overdue:
        state = "overdue"
    elif due_now > 0:
        state = "due"
    elif remaining > 0:
        state = "upcoming"
    else:
        state = "done"

    inventory = _compute_inventory(med, day, settings)

    return {
        "id": med.get("id") or slugify(med.get("name", "med")),
        "name": med.get("name") or "Medication",
        "unit": unit,
        "notes": med.get("notes") or "",
        "instances": view_instances,
        "state": state,
        "next_due_iso": _iso(next_dt),
        "next_due_time": next_dt.strftime("%H:%M") if next_dt else None,
        "next_dose_label": next_dose_label,
        "last_taken_iso": _iso(last_taken_dt),
        "taken_today": taken,
        "skipped_today": skipped,
        "scheduled_today": scheduled,
        "remaining_today": remaining,
        "due_now": due_now,
        "overdue": overdue,
        "dose_summary": f"{taken}/{scheduled}",
        "inventory": inventory,
    }


def _compute_inventory(med: dict, day: date, settings) -> dict | None:
    inv = med.get("inventory")
    if not isinstance(inv, dict) or not inv.get("track"):
        return None
    try:
        remaining = float(inv.get("count") or 0)
    except (TypeError, ValueError):
        remaining = 0.0
    per_day = daily_dose_total(med, day)
    days_left = round(remaining / per_day, 1) if per_day > 0 else None
    low = (
        settings.low_stock_days > 0
        and days_left is not None
        and days_left < settings.low_stock_days
    )
    return {
        "track": True,
        "remaining": round(remaining, 3),
        "unit": med.get("unit") or "pill",
        "per_day": round(per_day, 3),
        "days_left": days_left,
        "low": bool(low),
    }


def compute_subject(subject: dict, subj_log: dict, now: datetime, settings) -> dict:
    """Build the runtime view for a subject and all its medications."""
    meds = []
    for med in subject.get("medications") or []:
        mid = med.get("id") or slugify(med.get("name", "med"))
        meds.append(compute_med(med, subj_log.get(mid, {}), now, settings))

    taken = sum(m["taken_today"] for m in meds)
    scheduled = sum(m["scheduled_today"] for m in meds)
    remaining = sum(m["remaining_today"] for m in meds)
    due_now = sum(m["due_now"] for m in meds)
    overdue = any(m["overdue"] for m in meds)

    next_dt = None
    next_med = None
    next_dose = None
    for m in meds:
        if m["next_due_iso"]:
            dt = datetime.fromisoformat(m["next_due_iso"])
            if next_dt is None or dt < next_dt:
                next_dt = dt
                next_med = m["name"]
                next_dose = m["next_dose_label"]

    if next_med and next_dt:
        summary = f"{next_dose} of {next_med} at {next_dt.strftime('%H:%M')}"
    elif scheduled == 0:
        summary = "No medications scheduled"
    else:
        summary = "All done for today"

    return {
        "id": subject.get("id") or slugify(subject.get("name", "subject")),
        "name": subject.get("name") or "Subject",
        "kind": subject.get("kind") or "person",
        "medications": meds,
        "taken_today": taken,
        "scheduled_today": scheduled,
        "remaining_today": remaining,
        "due_now": due_now,
        "overdue": overdue,
        "next_due_iso": next_dt.isoformat() if next_dt else None,
        "next_due_time": next_dt.strftime("%H:%M") if next_dt else None,
        "next_med": next_med or "none",
        "next_summary": summary,
    }


def compute_model(subjects: list, history_day: dict, now: datetime, settings) -> dict:
    """Build the whole runtime model for today across every subject + the hub."""
    subj_views = []
    for subject in subjects:
        sid = subject.get("id") or slugify(subject.get("name", "subject"))
        subj_views.append(compute_subject(subject, history_day.get(sid, {}), now, settings))

    total_due = sum(s["due_now"] for s in subj_views)
    overdue = any(s["overdue"] for s in subj_views)

    next_dt = None
    next_subj = None
    next_summary = None
    due_list = []
    for s in subj_views:
        for m in s["medications"]:
            if m["due_now"] > 0:
                due_list.append({
                    "subject": s["name"],
                    "medication": m["name"],
                    "dose": m["next_dose_label"],
                    "state": m["state"],
                    "due_at": m["next_due_iso"],
                })
        if s["next_due_iso"]:
            dt = datetime.fromisoformat(s["next_due_iso"])
            if next_dt is None or dt < next_dt:
                next_dt = dt
                next_subj = s
                next_summary = f"{s['name']}: {s['next_summary']}"

    if total_due > 0:
        hub_summary = f"{total_due} dose(s) due now"
    elif next_summary:
        hub_summary = f"Next — {next_summary}"
    else:
        hub_summary = "Nothing due"

    return {
        "generated_iso": now.astimezone().isoformat(),
        "date": now.date().isoformat(),
        "hub": {
            "total_due": total_due,
            "overdue": overdue,
            "next_due_iso": next_dt.isoformat() if next_dt else None,
            "next_summary": hub_summary,
            "due_list": due_list,
        },
        "subjects": subj_views,
    }


# --- Action targeting ------------------------------------------------------
# These pick which instance an action applies to, from a computed medication
# view. They return the instance key (and dose), so the caller can record it.

def _untaken(med_view: dict):
    return [i for i in med_view["instances"] if i["status"] not in ("taken", "skipped")]


def choose_take(med_view: dict, allow_early: bool):
    """The instance a Take press should mark: the earliest due/overdue one, or
    (if allowed) the earliest upcoming one."""
    actionable = [i for i in _untaken(med_view) if i["status"] in ("due", "overdue")]
    if actionable:
        return actionable[0]
    if allow_early:
        upcoming = [i for i in _untaken(med_view) if i["status"] == "upcoming"]
        if upcoming:
            return upcoming[0]
    return None


def choose_skip(med_view: dict):
    """The instance a Skip press should mark: the earliest not-yet-handled one."""
    untaken = _untaken(med_view)
    return untaken[0] if untaken else None


def choose_undo(med_view: dict, med_log: dict):
    """The most recently taken instance today (to undo). Returns the instance
    view dict or None."""
    taken = [i for i in med_view["instances"] if i["status"] == "taken"]
    if not taken:
        return None

    def _when(i):
        rec = med_log.get(i["key"]) or {}
        at = rec.get("at")
        try:
            return datetime.fromisoformat(at) if at else i["at"]
        except ValueError:
            return i["at"]

    taken.sort(key=_when)
    return taken[-1]
