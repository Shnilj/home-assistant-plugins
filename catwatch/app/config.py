"""Configuration loading and shared paths.

Add-on options are written by the Supervisor to ``/data/options.json``. Runtime
UI settings that the app itself edits (the zones) live in
``/config/settings.json`` so they persist and are user-visible.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field

# --- Directories -----------------------------------------------------------
DATA_DIR = os.environ.get("DATA_DIR", "/data")
CONFIG_DIR = os.environ.get("CONFIG_DIR", "/config")

OPTIONS_PATH = os.path.join(DATA_DIR, "options.json")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")
EVENTS_PATH = os.path.join(CONFIG_DIR, "events.json")
MODEL_PATH = os.path.join(DATA_DIR, "model.npz")

# Bundled recognition model. Resolves to catwatch/models/... from source and
# /app/models/... inside the container (both are <package parent>/models).
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMBED_MODEL_PATH = os.environ.get(
    "EMBED_MODEL_PATH", os.path.join(_PKG_ROOT, "models", "mobilenetv2-12.onnx")
)

SNAP_DIR = os.path.join(CONFIG_DIR, "snapshots")
DATASET_DIR = os.path.join(CONFIG_DIR, "dataset")
UNLABELED_DIR = os.path.join(DATASET_DIR, "_unlabeled")

# Reserved dataset folder names that are not real cat labels.
RESERVED_LABELS = {"_unlabeled"}

ZONE_TYPES = ("food", "water")

_DEFAULTS = {
    "rtsp_url": "",
    "detection_fps": 3,
    "motion_sensitivity": 25,
    "motion_min_area": 1500,
    "eating_dwell_seconds": 5,
    "meal_cooldown_minutes": 15,
    "drink_dwell_seconds": 3,
    "drink_cooldown_minutes": 10,
    "presence_grace_seconds": 3,
    "zone_coverage": 0.3,
    "require_lean_in": True,
    "history_hours": 24,
    "recognizer": "embedding",
    "recognition_margin": 0.6,
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
    drink_dwell_seconds: int = 3
    drink_cooldown_minutes: int = 10
    presence_grace_seconds: int = 3
    zone_coverage: float = 0.3
    require_lean_in: bool = True
    history_hours: int = 24
    recognizer: str = "embedding"
    recognition_margin: float = 0.6
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

    def dwell_for(self, action: str) -> int:
        return self.drink_dwell_seconds if action == "drinking" else self.eating_dwell_seconds

    def cooldown_for(self, action: str) -> int:
        return (
            self.drink_cooldown_minutes if action == "drinking" else self.meal_cooldown_minutes
        )


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
        drink_dwell_seconds=_int("drink_dwell_seconds"),
        drink_cooldown_minutes=_int("drink_cooldown_minutes"),
        presence_grace_seconds=_int("presence_grace_seconds"),
        zone_coverage=float(opts.get("zone_coverage", 0.3)),
        require_lean_in=bool(opts.get("require_lean_in", True)),
        history_hours=_int("history_hours"),
        recognizer=str(opts.get("recognizer", "embedding")).lower(),
        recognition_margin=float(opts.get("recognition_margin", 0.6)),
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


# --- Zones -----------------------------------------------------------------
def _valid_zone(z) -> dict | None:
    """Coerce a raw dict into a valid zone, or return None."""
    if not isinstance(z, dict):
        return None
    ztype = z.get("type")
    rect = z.get("rect")
    if ztype not in ZONE_TYPES:
        return None
    if not (isinstance(rect, (list, tuple)) and len(rect) == 4):
        return None
    try:
        rect = [int(v) for v in rect]
    except (TypeError, ValueError):
        return None
    if rect[2] < 4 or rect[3] < 4:
        return None
    default_name = "Food bowl" if ztype == "food" else "Water"
    return {
        "id": str(z.get("id") or uuid.uuid4().hex[:8]),
        "name": str(z.get("name") or default_name),
        "type": ztype,
        "rect": rect,
    }


def load_zones() -> list:
    """Return the list of valid zones. Migrates a legacy single ``roi`` to one
    food zone so existing setups keep working."""
    data = _read_json(SETTINGS_PATH)
    zones = []
    raw = data.get("zones")
    if isinstance(raw, list):
        for z in raw:
            v = _valid_zone(z)
            if v:
                zones.append(v)
    if not zones:
        roi = data.get("roi")
        if isinstance(roi, list) and len(roi) == 4:
            v = _valid_zone({"id": "legacy", "name": "Food bowl", "type": "food", "rect": roi})
            if v:
                zones = [v]
    return zones


def save_zones(zones) -> None:
    valid = []
    if isinstance(zones, list):
        for z in zones:
            v = _valid_zone(z)
            if v:
                valid.append(v)
    data = _read_json(SETTINGS_PATH)
    data["zones"] = valid
    data.pop("roi", None)  # legacy key no longer used
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def ensure_dirs(settings: Settings) -> None:
    for d in (DATA_DIR, CONFIG_DIR, SNAP_DIR, DATASET_DIR, UNLABELED_DIR):
        os.makedirs(d, exist_ok=True)
    for slug, name in settings.cat_slugs.items():
        os.makedirs(os.path.join(DATASET_DIR, name), exist_ok=True)
