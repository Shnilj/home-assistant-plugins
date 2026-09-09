"""Daily statistics — a small persistent per-day aggregate.

Independent of the snapshot history (which is pruned within hours), so it can
power weekly summaries and trends, and act as the durable source of truth for the
daily counters. Shape:

    { "YYYY-MM-DD": { "<cat>": {meals, drinks, eat_sec, drink_sec} } }

A `version` counter is bumped on every mutation so the processing loop can notice
changes made by the web thread (corrections/deletes) and re-publish.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import date, timedelta

log = logging.getLogger("catwatch.stats")

_ZERO = {"meals": 0, "drinks": 0, "eat_sec": 0, "drink_sec": 0}
# action -> (count key, seconds key)
_KEYS = {"eating": ("meals", "eat_sec"), "drinking": ("drinks", "drink_sec")}


def _today() -> str:
    return date.today().isoformat()


class DailyStats:
    def __init__(self, path: str, keep_days: int = 120):
        self.path = path
        self.keep_days = keep_days
        self.version = 0
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, ValueError):
            return {}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh)
            os.replace(tmp, self.path)
        except OSError as exc:
            log.warning("Could not write stats: %s", exc)

    def _bucket(self, day: str, cat: str) -> dict:
        d = self._data.setdefault(day, {})
        return d.setdefault(cat, dict(_ZERO))

    # -- mutations ----------------------------------------------------------
    def add_event(self, cat: str, action: str, day: str = None) -> None:
        if action not in _KEYS:
            return
        with self._lock:
            self._bucket(day or _today(), cat)[_KEYS[action][0]] += 1
            self.version += 1
            self._save()

    def add_duration(self, cat: str, action: str, seconds: int, day: str = None) -> None:
        if action not in _KEYS or seconds <= 0:
            return
        with self._lock:
            self._bucket(day or _today(), cat)[_KEYS[action][1]] += int(seconds)
            self.version += 1
            self._save()

    def adjust(self, day: str, cat: str, action: str, d_count: int = 0, d_seconds: int = 0) -> None:
        """Apply deltas (used by corrections/deletes). Never goes below zero."""
        if action not in _KEYS:
            return
        ck, sk = _KEYS[action]
        with self._lock:
            b = self._bucket(day, cat)
            b[ck] = max(0, b[ck] + d_count)
            b[sk] = max(0, b[sk] + d_seconds)
            self.version += 1
            self._save()

    def prune(self) -> None:
        cutoff = (date.today() - timedelta(days=self.keep_days)).isoformat()
        with self._lock:
            old = [d for d in self._data if d < cutoff]
            for d in old:
                del self._data[d]
            if old:
                self.version += 1
                self._save()

    # -- reads --------------------------------------------------------------
    def count(self, cat: str, action: str, day: str = None) -> int:
        ck = _KEYS[action][0]
        with self._lock:
            return self._data.get(day or _today(), {}).get(cat, _ZERO)[ck]

    def today_counts(self, cat: str) -> dict:
        with self._lock:
            b = self._data.get(_today(), {}).get(cat, _ZERO)
            return {"eating": b["meals"], "drinking": b["drinks"]}

    def week_totals(self, cat: str) -> dict:
        days = [(date.today() - timedelta(days=i)).isoformat() for i in range(7)]
        tot = dict(_ZERO)
        with self._lock:
            for d in days:
                b = self._data.get(d, {}).get(cat)
                if b:
                    for k in tot:
                        tot[k] += b.get(k, 0)
        return tot

    def last_days(self, n: int, cats) -> list:
        """List oldest→newest: [{date, cats:{cat:{meals,drinks,eat_sec,drink_sec}}}]."""
        out = []
        with self._lock:
            for i in range(n - 1, -1, -1):
                d = (date.today() - timedelta(days=i)).isoformat()
                day = self._data.get(d, {})
                out.append({"date": d, "cats": {c: dict(day.get(c, _ZERO)) for c in cats}})
        return out
