"""Thread-safe controller shared by the processing loop, the web UI and MQTT.

Owns the in-memory config + history, serialises all mutations behind a lock, and
exposes the high-level actions (take / skip / undo / take-all-due, save config).
Scheduling maths lives in ``schedule.py``; persistence in ``store.py``.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime

from . import schedule, store

log = logging.getLogger("medtracker.controller")


class Controller:
    def __init__(self, settings):
        self.s = settings
        self._lock = threading.RLock()
        self._config = store.load_config()
        self._config_mtime = store.config_mtime()
        self._history = store.prune_history(store.load_history(), settings.history_days)
        self.dirty = threading.Event()   # set when state changed → force republish

    # -- config -------------------------------------------------------------
    def reload_config_if_changed(self) -> bool:
        """Pick up external edits to medications.json (e.g. via File editor)."""
        with self._lock:
            mtime = store.config_mtime()
            if mtime and mtime != self._config_mtime:
                self._config = store.load_config()
                self._config_mtime = mtime
                log.info("Reloaded medications.json (changed on disk)")
                self.dirty.set()
                return True
        return False

    def get_config(self) -> dict:
        with self._lock:
            return self._config

    def save_config(self, data) -> dict:
        with self._lock:
            self._config = store.save_config(data)
            self._config_mtime = store.config_mtime()
            self.dirty.set()
            return self._config

    def subjects(self) -> list:
        return self.get_config().get("subjects", [])

    def _find(self, sid, mid=None):
        for s in self.get_config().get("subjects", []):
            if s["id"] == sid:
                if mid is None:
                    return s, None
                for m in s.get("medications", []):
                    if m["id"] == mid:
                        return s, m
        return None, None

    # -- model --------------------------------------------------------------
    def model(self, now: datetime | None = None) -> dict:
        now = now or datetime.now()
        with self._lock:
            day_log = store.day_log(self._history, now.date().isoformat())
            return schedule.compute_model(self.subjects(), day_log, now, self.s)

    def _med_view(self, sid, mid, now):
        _s, med = self._find(sid, mid)
        if med is None:
            return None, None
        med_log = (
            self._history.get(now.date().isoformat(), {}).get(sid, {}).get(mid, {})
        )
        return med, schedule.compute_med(med, med_log, now, self.s)

    # -- inventory ----------------------------------------------------------
    def _adjust_inventory(self, med, delta) -> bool:
        inv = med.get("inventory") or {}
        if not inv.get("track"):
            return False
        try:
            count = float(inv.get("count") or 0)
        except (TypeError, ValueError):
            count = 0.0
        inv["count"] = round(max(0.0, count + delta), 3)
        med["inventory"] = inv
        return True

    def _persist(self, inventory_changed: bool):
        store.save_history(self._history)
        if inventory_changed:
            self._config = store.save_config(self._config)
            self._config_mtime = store.config_mtime()
        self.dirty.set()

    # -- actions ------------------------------------------------------------
    def take(self, sid, mid, now=None) -> bool:
        now = now or datetime.now()
        with self._lock:
            med, view = self._med_view(sid, mid, now)
            if view is None:
                return False
            inst = schedule.choose_take(view, self.s.allow_take_early)
            if inst is None:
                log.info("Take: nothing actionable for %s/%s", sid, mid)
                return False
            store.record(self._history, now.date().isoformat(), sid, mid,
                        inst["key"], "taken", now.astimezone().isoformat(), inst["dose"])
            inv_changed = self._adjust_inventory(med, -inst["dose"])
            log.info("Taken: %s/%s @ %s (%s)", sid, mid, inst["key"], inst["dose_label"])
            self._persist(inv_changed)
            return True

    def skip(self, sid, mid, now=None) -> bool:
        now = now or datetime.now()
        with self._lock:
            med, view = self._med_view(sid, mid, now)
            if view is None:
                return False
            inst = schedule.choose_skip(view)
            if inst is None:
                return False
            store.record(self._history, now.date().isoformat(), sid, mid,
                        inst["key"], "skipped", now.astimezone().isoformat(), inst["dose"])
            log.info("Skipped: %s/%s @ %s", sid, mid, inst["key"])
            self._persist(False)
            return True

    def undo(self, sid, mid, now=None) -> bool:
        now = now or datetime.now()
        with self._lock:
            med, view = self._med_view(sid, mid, now)
            if view is None:
                return False
            med_log = (
                self._history.get(now.date().isoformat(), {}).get(sid, {}).get(mid, {})
            )
            inst = schedule.choose_undo(view, med_log)
            if inst is None:
                return False
            rec = store.unrecord(self._history, now.date().isoformat(), sid, mid, inst["key"])
            inv_changed = False
            if rec and rec.get("status") == "taken":
                inv_changed = self._adjust_inventory(med, float(rec.get("dose") or 0))
            log.info("Undo: %s/%s @ %s", sid, mid, inst["key"])
            self._persist(inv_changed)
            return True

    def take_all_due(self, sid, now=None) -> int:
        """Mark every currently due/overdue dose for a subject as taken (across
        all its medications, and every due instance of each). Returns how many
        doses were taken."""
        now = now or datetime.now()
        n = 0
        subj, _ = self._find(sid)
        if subj is None:
            return 0
        for med in list(subj.get("medications", [])):
            guard = 0
            while guard < 32:
                _m, view = self._med_view(sid, med["id"], now)
                if not view or view["due_now"] <= 0:
                    break
                if not self.take(sid, med["id"], now):
                    break
                n += 1
                guard += 1
        return n

    # -- persistence maintenance -------------------------------------------
    def prune(self):
        with self._lock:
            store.prune_history(self._history, self.s.history_days)
