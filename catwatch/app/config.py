"""Configuration loading and shared paths.

Add-on options are written by the Supervisor to ``/data/options.json``. Runtime
UI settings that the app itself edits (currently the ROI) live in
``/config/settings.json`` so they persist and are user-visible.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

# --- Directories -----------------------------------------------------------
DATA_DIR = os.environ.get("DATA_DIR", "/data")
CONFIG_DIR = os.environ.get("CONFIG_DIR", "/config")

OPTIONS_PATH = os.path.join(DATA_DIR, "options.json")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")
MODEL_PATH = os.path.join(DATA_DIR, "model.npz")

SNAP_DIR = os.path.join(CONFIG_DIR, "snapshots")
DATASET_DIR = os.path.join(CONFIG_DIR, "dataset")
UNLABELED_DIR = os.path.join(DATASET_DIR, "_unlabeled")

# Reserved dataset folder names that are not real cat labels.
RESERVED_LABELS = {"_unlabeled"}

_DEFAULTS = {
    "rtsp_url": "",
    "detection_fps": 3,
    "motion_sensitivity": 25,
    "motion_min_area": 1500,
    "eating_dwell_seconds": 5,
    "meal_cooldown_minutes": 15,
    "presence_grace_seconds": 3,
    "cats": ["Ellie"],
    "classifier_confidence": 0.55,
    "save_captures": True,
    "jpeg_quality": 80,
    "log_level": "info",
}


def slugify(name: str) -> str:
    """Turn a cat name into an entity/topic-safe slug."""
    slug = re.sub(r"[^a-z0-9_]+", "_", name.strip().lower())
    return slug.strip("_") or "cat"


def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return {}


@dataclass
class Settings:
    rtsp_url: str = ""
    detection_fps: int = 3
    motion_sensitivity: int = 25
    motion_min_area: int = 1500
    eating_dwell_seconds: int = 5
    meal_cooldown_minutes: int = 15
    presence_grace_seconds: int = 3
    cats: list = field(default_factory=lambda: ["Ellie"])
    classifier_confidence: float = 0.55
    save_captures: bool = True
    jpeg_quality: int = 80
    log_level: str = "info"

    # MQTT (from environment, injected by run.sh via bashio)
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_user: str = ""
    mqtt_password: str = ""

    @property
    def cat_slugs(self) -> dict:
        """Map slug -> display name for every configured cat."""
        return {slugify(c): c for c in self.cats}

    def dataset_dir_for(self, label: str) -> str:
        return os.path.join(DATASET_DIR, label)


def load_settings() -> Settings:
    opts = {**_DEFAULTS, **_read_json(OPTIONS_PATH)}

    def _int(key):
        try:
            return int(opts.get(key))
        except (TypeError, ValueError):
            return _DEFAULTS[key]

    cats = opts.get("cats") or _DEFAULTS["cats"]
    if not isinstance(cats, list):
        cats = _DEFAULTS["cats"]

    return Settings(
        rtsp_url=str(opts.get("rtsp_url", "")).strip(),
        detection_fps=max(1, _int("detection_fps")),
        motion_sensitivity=_int("motion_sensitivity"),
        motion_min_area=_int("motion_min_area"),
        eating_dwell_seconds=_int("eating_dwell_seconds"),
        meal_cooldown_minutes=_int("meal_cooldown_minutes"),
        presence_grace_seconds=_int("presence_grace_seconds"),
        cats=[str(c) for c in cats if str(c).strip()],
        classifier_confidence=float(opts.get("classifier_confidence", 0.55)),
        save_captures=bool(opts.get("save_captures", True)),
        jpeg_quality=_int("jpeg_quality"),
        log_level=str(opts.get("log_level", "info")).lower(),
        mqtt_host=os.environ.get("MQTT_HOST", ""),
        mqtt_port=int(os.environ.get("MQTT_PORT", "1883") or 1883),
        mqtt_user=os.environ.get("MQTT_USER", ""),
        mqtt_password=os.environ.get("MQTT_PASSWORD", ""),
    )


def load_roi() -> list | None:
    """Return [x, y, w, h] in pixels, or None for the whole frame."""
    roi = _read_json(SETTINGS_PATH).get("roi")
    if isinstance(roi, list) and len(roi) == 4:
        try:
            return [int(v) for v in roi]
        except (TypeError, ValueError):
            return None
    return None


def save_roi(roi: list | None) -> None:
    data = _read_json(SETTINGS_PATH)
    if roi is None:
        data.pop("roi", None)
    else:
        data["roi"] = [int(v) for v in roi]
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def ensure_dirs(settings: Settings) -> None:
    for d in (DATA_DIR, CONFIG_DIR, SNAP_DIR, DATASET_DIR, UNLABELED_DIR):
        os.makedirs(d, exist_ok=True)
    for slug, name in settings.cat_slugs.items():
        os.makedirs(os.path.join(DATASET_DIR, name), exist_ok=True)
