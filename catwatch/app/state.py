"""Thread-safe state shared between the processing loop and the web UI."""
from __future__ import annotations

import threading


class SharedState:
    def __init__(self, cat_names):
        self._lock = threading.Lock()
        self.latest_frame_jpg = None      # newest raw camera frame (for zone editor)
        self.latest_snapshot_jpg = None   # newest event snapshot (annotated)
        self.status = {
            "camera_connected": False,
            "activity": False,
            "current_cat": "none",
            "current_confidence": 0.0,
            "current_zone": "none",
            "current_action": "none",
            "current_elapsed": 0,
            "model_ready": False,
            "mqtt_connected": False,
        }
        self.cats = {
            name: {
                "eating": False,
                "drinking": False,
                "last_eaten": None,
                "last_drank": None,
                "meals_today": 0,
                "drinks_today": 0,
                "last_meal_duration": None,
                "last_drink_duration": None,
            }
            for name in cat_names
        }

    def set_frame(self, jpg):
        with self._lock:
            self.latest_frame_jpg = jpg

    def get_frame(self):
        with self._lock:
            return self.latest_frame_jpg

    def set_snapshot(self, jpg):
        with self._lock:
            self.latest_snapshot_jpg = jpg

    def get_snapshot(self):
        with self._lock:
            return self.latest_snapshot_jpg

    def update_status(self, **kwargs):
        with self._lock:
            self.status.update(kwargs)

    def update_cat(self, name, **kwargs):
        with self._lock:
            if name in self.cats:
                self.cats[name].update(kwargs)

    def snapshot_status(self):
        with self._lock:
            return {"status": dict(self.status), "cats": {k: dict(v) for k, v in self.cats.items()}}


class ModelHolder:
    """Holds the active model so the web UI can swap it in after retraining."""

    def __init__(self, model):
        self._model = model
        self._lock = threading.Lock()

    def get(self):
        with self._lock:
            return self._model

    def set(self, model):
        with self._lock:
            self._model = model
