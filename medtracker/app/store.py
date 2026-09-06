"""Persistence for MedTracker.

Two JSON files:
  - /config/medications.json — the schedule the user edits (subjects, meds).
    User-visible so it can be inspected/backed up via Samba / the File editor.
  - /data/history.json       — internal dose history: which instances were
    taken/skipped, when. Pruned to ``history_days``.

All functions here are plain IO + validation; no scheduling logic (that lives in
``schedule.py``) and no threading (the controller owns the lock).
"""
from __future__ import annotations

import json
import os
import tempfile

from . import config
from .schedule import SCHEDULE_TYPES, parse_hhmm, slugify

VALID_KINDS = ("person", "animal", "other")


# --- low-level IO ----------------------------------------------------------
def _read_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return default


def _atomic_write(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def config_mtime() -> float:
    try:
        return os.path.getmtime(config.MEDICATIONS_PATH)
    except OSError:
        return 0.0


# --- config validation -----------------------------------------------------
def _norm_time(value) -> str | None:
    try:
        return parse_hhmm(value).strftime("%H:%M")
    except (ValueError, AttributeError, TypeError):
        return None


def _pos_float(value, default=1.0):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if v > 0 else default


def _normalize_schedule(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    stype = raw.get("type")
    if stype not in SCHEDULE_TYPES:
        stype = "times"

    if stype == "interval":
        start = _norm_time(raw.get("start")) or "08:00"
        end = _norm_time(raw.get("end")) or "22:00"
        every = raw.get("every_hours")
        try:
            every = float(every)
        except (TypeError, ValueError):
            every = 4.0
        if every <= 0:
            every = 4.0
        # keep an int if it is whole (cleaner file)
        every = int(every) if float(every).is_integer() else every
        return {
            "type": "interval",
            "every_hours": every,
            "start": start,
            "end": end,
            "dose": _pos_float(raw.get("dose"), 1.0),
        }

    times = []
    for entry in raw.get("times") or []:
        if not isinstance(entry, dict):
            continue
        t = _norm_time(entry.get("time"))
        if not t:
            continue
        times.append({"time": t, "dose": _pos_float(entry.get("dose"), 1.0)})
    times.sort(key=lambda e: e["time"])
    if not times:
        times = [{"time": "08:00", "dose": 1.0}]
    return {"type": "times", "times": times}


def _normalize_inventory(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    track = bool(raw.get("track"))
    try:
        count = float(raw.get("count"))
    except (TypeError, ValueError):
        count = 0.0
    return {"track": track, "count": round(max(0.0, count), 3)}


def _unique(base: str, used: set) -> str:
    sid = base
    n = 2
    while sid in used:
        sid = f"{base}_{n}"
        n += 1
    used.add(sid)
    return sid


def normalize_config(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    subjects = []
    used_sids: set = set()
    for s in raw.get("subjects") or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "Subject").strip() or "Subject"
        sid = _unique(s.get("id") or slugify(name), used_sids)
        kind = s.get("kind") if s.get("kind") in VALID_KINDS else "person"

        meds = []
        used_mids: set = set()
        for m in s.get("medications") or []:
            if not isinstance(m, dict):
                continue
            mname = str(m.get("name") or "Medication").strip() or "Medication"
            mid = _unique(m.get("id") or slugify(mname), used_mids)
            meds.append({
                "id": mid,
                "name": mname,
                "unit": str(m.get("unit") or "pill").strip() or "pill",
                "notes": str(m.get("notes") or "").strip(),
                "schedule": _normalize_schedule(m.get("schedule")),
                "inventory": _normalize_inventory(m.get("inventory")),
            })

        subjects.append({"id": sid, "name": name, "kind": kind, "medications": meds})
    return {"subjects": subjects}


def load_config() -> dict:
    return normalize_config(_read_json(config.MEDICATIONS_PATH, {"subjects": []}))


def save_config(data) -> dict:
    norm = normalize_config(data)
    _atomic_write(config.MEDICATIONS_PATH, norm)
    return norm


# --- history ---------------------------------------------------------------
def load_history() -> dict:
    data = _read_json(config.HISTORY_PATH, {})
    return data if isinstance(data, dict) else {}


def save_history(history: dict) -> None:
    _atomic_write(config.HISTORY_PATH, history)


def prune_history(history: dict, keep_days: int) -> dict:
    if len(history) <= keep_days:
        return history
    for day in sorted(history.keys())[:-keep_days]:
        history.pop(day, None)
    return history


def day_log(history: dict, day_iso: str) -> dict:
    """The {sid: {mid: {instkey: record}}} map for a day (read-only helper)."""
    return history.get(day_iso, {})


def record(history: dict, day_iso: str, sid: str, mid: str, inst_key: str,
           status: str, at_iso: str, dose: float) -> None:
    history.setdefault(day_iso, {}).setdefault(sid, {}).setdefault(mid, {})[inst_key] = {
        "status": status,
        "at": at_iso,
        "dose": dose,
    }


def unrecord(history: dict, day_iso: str, sid: str, mid: str, inst_key: str) -> dict | None:
    try:
        rec = history[day_iso][sid][mid].pop(inst_key)
    except KeyError:
        return None
    return rec
