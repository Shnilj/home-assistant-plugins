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


# --- Recurrence / multi-day courses ----------------------------------------
# A medication may run on a cadence across days (a "course"): e.g. a B12 shot
# every week for 6 weeks, or an antibiotic twice a day for 5 days. The
# ``recurrence`` block gates WHICH DAYS the med is active; the intra-day schedule
# (times / interval) still decides the doses on an active day. A med with no
# ``recurrence`` is active every day (unchanged behaviour).

def parse_date(value):
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _cadence_step_days(rec) -> int:
    if rec.get("type") == "interval":
        every = int(rec.get("every") or 1)
        return max(1, every) * (7 if rec.get("unit") == "week" else 1)
    return 1


def is_occurrence(rec, day, start) -> bool:
    """True if ``day`` matches the cadence (ignoring the end window)."""
    t = rec.get("type", "daily")
    if start and day < start:
        return False
    if t == "interval":
        if not start:
            return True
        return (day - start).days % _cadence_step_days(rec) == 0
    if t == "weekdays":
        return day.weekday() in (rec.get("weekdays") or [])
    return True  # daily


def occurrence_index(rec, day, start):
    """0-based index of ``day`` among cadence occurrences from ``start``, or None
    if ``day`` is not itself an occurrence."""
    if not is_occurrence(rec, day, start):
        return None
    t = rec.get("type", "daily")
    if not start:
        return 0
    if t == "interval":
        return (day - start).days // _cadence_step_days(rec)
    if t == "weekdays":
        wd = set(rec.get("weekdays") or [])
        count, d, guard = 0, start, 0
        while d <= day and guard < 10000:
            if d.weekday() in wd:
                count += 1
            d += timedelta(days=1)
            guard += 1
        return count - 1
    return (day - start).days  # daily


def _end_count(rec):
    end = rec.get("end") or {}
    if end.get("type") == "count":
        try:
            return int(end.get("count"))
        except (TypeError, ValueError):
            return None
    return None


def _end_until(rec):
    end = rec.get("end") or {}
    if end.get("type") == "date":
        return parse_date(end.get("until"))
    return None


def is_active_on(med: dict, day: date) -> bool:
    """Whether ``med`` has any doses scheduled on ``day`` — cadence AND the
    course window (start date, and end after N times or on a date)."""
    rec = med.get("recurrence")
    if not rec:
        return True
    start = parse_date(rec.get("start"))
    if start and day < start:
        return False
    if not is_occurrence(rec, day, start):
        return False
    until = _end_until(rec)
    if until and day > until:
        return False
    count = _end_count(rec)
    if count is not None:
        idx = occurrence_index(rec, day, start)
        if idx is None or idx >= count:
            return False
    return True


def next_active_day(med: dict, from_day: date, horizon: int = 800):
    day = from_day
    for _ in range(horizon):
        if is_active_on(med, day):
            return day
        day += timedelta(days=1)
    return None


def _occurrence_date(rec, start, n):
    """Date of the n-th (0-based) cadence occurrence from ``start``."""
    if not start:
        return None
    t = rec.get("type", "daily")
    if t == "interval":
        return start + timedelta(days=n * _cadence_step_days(rec))
    if t == "weekdays":
        wd = set(rec.get("weekdays") or [])
        if not wd:
            return None
        count, d, guard = -1, start, 0
        while guard < 10000:
            if d.weekday() in wd:
                count += 1
                if count == n:
                    return d
            d += timedelta(days=1)
            guard += 1
        return None
    return start + timedelta(days=n)  # daily


def course_info(med: dict, now: datetime):
    """A human summary of a med's multi-day course, or None for a plain med
    (no recurrence, or daily-forever)."""
    rec = med.get("recurrence")
    if not rec:
        return None
    if rec.get("type", "daily") == "daily" and not (rec.get("end") and rec["end"].get("type") in ("count", "date")):
        return None  # daily forever — not really a "course"

    today = now.date()
    start = parse_date(rec.get("start"))
    ref = today if is_active_on(med, today) else next_active_day(med, today)
    total = _end_count(rec)
    until = _end_until(rec)

    index = None
    if ref is not None and start is not None:
        idx = occurrence_index(rec, ref, start)
        index = (idx + 1) if idx is not None else None

    end_date = until
    if end_date is None and total is not None and start is not None:
        end_date = _occurrence_date(rec, start, total - 1)

    active = is_active_on(med, today) or (next_active_day(med, today) is not None)

    if total and index:
        summary = f"{index} of {total}"
    elif until:
        summary = f"until {until.isoformat()}"
    else:
        summary = "ongoing"
    if not active:
        summary = "finished"

    return {
        "active": bool(active),
        "index": index,
        "total": total,
        "summary": summary,
        "start_iso": start.isoformat() if start else None,
        "end_date_iso": end_date.isoformat() if end_date else None,
    }


def compute_med(med: dict, med_log: dict, now: datetime, settings) -> dict:
    """Build the full runtime view for a single medication, including a look
    ahead to its next scheduled day when nothing remains due today."""
    day = now.date()
    unit = med.get("unit") or "pill"
    active_today = is_active_on(med, day)
    insts = med_instances(med, day) if active_today else []

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

    # Look ahead: nothing left due today (all handled, or not active today) → the
    # next due time is the first dose on the next active day. Works for daily
    # meds (tomorrow) and for weekly/interval courses (next week, next dose date).
    next_is_future = False
    if next_dt is None:
        search_from = day + timedelta(days=1) if active_today else day
        nd = next_active_day(med, search_from)
        if nd is not None:
            future = med_instances(med, nd)
            if future:
                next_dt = future[0].at
                next_dose_label = format_dose(future[0].dose, unit)
                next_is_future = True

    if scheduled > 0:
        if remaining == 0:
            state = "done"
        elif overdue:
            state = "overdue"
        elif due_now > 0:
            state = "due"
        else:
            state = "upcoming"
    else:
        state = "upcoming" if next_dt is not None else "none"

    inventory = _compute_inventory(med, day, settings)
    course = course_info(med, now)

    return {
        "id": med.get("id") or slugify(med.get("name", "med")),
        "name": med.get("name") or "Medication",
        "unit": unit,
        "notes": med.get("notes") or "",
        "instances": view_instances,
        "active_today": active_today,
        "state": state,
        "next_due_iso": _iso(next_dt),
        "next_due_time": next_dt.strftime("%H:%M") if next_dt else None,
        "next_due_date": next_dt.date().isoformat() if next_dt else None,
        "next_is_future": next_is_future,
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
        "course": course,
    }


def _effective_daily_dose(med: dict, day: date) -> float:
    """Average dose per calendar day, accounting for a multi-day cadence (a
    weekly shot consumes ~1/7 of a dose per day) — used for inventory days-left."""
    per_active_day = daily_dose_total(med, day)
    rec = med.get("recurrence")
    if not rec:
        return per_active_day
    t = rec.get("type", "daily")
    if t == "interval":
        return per_active_day / _cadence_step_days(rec)
    if t == "weekdays":
        n = len(rec.get("weekdays") or []) or 1
        return per_active_day * n / 7.0
    return per_active_day  # daily


def _compute_inventory(med: dict, day: date, settings) -> dict | None:
    inv = med.get("inventory")
    if not isinstance(inv, dict) or not inv.get("track"):
        return None
    try:
        remaining = float(inv.get("count") or 0)
    except (TypeError, ValueError):
        remaining = 0.0
    per_day = _effective_daily_dose(med, day)
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
        when = next_dt.strftime("%H:%M")
        if next_dt.date() != now.date():
            when = next_dt.strftime("%a %d %b %H:%M")
        summary = f"{next_dose} of {next_med} at {when}"
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


def latest_taken(history: dict, sid: str, mid: str):
    """Most recent 'taken' timestamp for a medication across the WHOLE history
    (all days), or None. Used for a persistent "last given" that survives across
    days — unlike the per-day view, which only knows about today."""
    best = None
    for day, subs in (history or {}).items():
        if day == "_last_given" or not isinstance(subs, dict):
            continue
        recs = (subs.get(sid, {}) or {}).get(mid, {}) or {}
        if not isinstance(recs, dict):
            continue
        for r in recs.values():
            if isinstance(r, dict) and r.get("status") == "taken" and r.get("at"):
                try:
                    dt = datetime.fromisoformat(r["at"])
                except (ValueError, TypeError):
                    continue
                if best is None or dt > best:
                    best = dt
    # The persistent marker survives history pruning; fold it in.
    marker = ((history or {}).get("_last_given", {}) or {}).get(sid, {}).get(mid)
    if marker:
        try:
            mdt = datetime.fromisoformat(marker)
            if best is None or mdt > best:
                best = mdt
        except (ValueError, TypeError):
            pass
    return best.isoformat() if best else None


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
                    "subject_id": s["id"],
                    "medication": m["name"],
                    "med_id": m["id"],
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
