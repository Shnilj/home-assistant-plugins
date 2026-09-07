"""Event history — a rolling archive of eating/drinking events.

Each counted event is one record: which cat, what action, which zone, when, and
the snapshot filename. Records (and their snapshot files) older than the
retention window are pruned. Persisted to a small JSON file in /config so it
survives restarts and is user-visible.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime

log = logging.getLogger("catwatch.history")


def _epoch(iso_ts: str) -> float:
    try:
        return datetime.fromisoformat(iso_ts).timestamp()
    except (ValueError, TypeError):
        return 0.0


class EventLog:
    def __init__(self, path: str, snap_dir: str, max_events: int = 1000):
        self.path = path
        self.snap_dir = snap_dir
        self.max_events = max_events
        self._lock = threading.Lock()
        self._events = self._load()

    def _load(self) -> list:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (FileNotFoundError, ValueError):
            return []

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._events, fh)
            os.replace(tmp, self.path)
        except OSError as exc:
            log.warning("Could not write event log: %s", exc)

    def _delete_snapshot(self, event: dict) -> None:
        name = event.get("snapshot")
        if not name:
            return
        try:
            os.remove(os.path.join(self.snap_dir, os.path.basename(name)))
        except OSError:
            pass

    def add(self, cat, action, zone, snapshot, ts_iso) -> None:
        event = {"ts": ts_iso, "cat": cat, "action": action, "zone": zone, "snapshot": snapshot}
        with self._lock:
            self._events.append(event)
            if len(self._events) > self.max_events:
                overflow = self._events[: len(self._events) - self.max_events]
                self._events = self._events[len(overflow):]
                for e in overflow:
                    self._delete_snapshot(e)
            self._save()

    def prune(self, max_age_seconds: float) -> int:
        cutoff = datetime.now().timestamp() - max_age_seconds
        removed = 0
        with self._lock:
            keep = []
            for e in self._events:
                if _epoch(e.get("ts", "")) >= cutoff:
                    keep.append(e)
                else:
                    self._delete_snapshot(e)
                    removed += 1
            if removed:
                self._events = keep
                self._save()
        return removed

    def list(self, limit: int = 300) -> list:
        """Newest first."""
        with self._lock:
            return list(reversed(self._events[-limit:]))
