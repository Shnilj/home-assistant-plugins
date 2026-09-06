"""Add-on options and shared paths.

Scalar tuning options are written by the Supervisor to ``/data/options.json``.
The medication schedule the app itself edits lives in ``/config/medications.json``
so it persists and is user-visible (browsable via Samba / the File editor
add-on). The dose history (taken / skipped records) lives in ``/data`` because it
is internal state.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

# --- Directories -----------------------------------------------------------
DATA_DIR = os.environ.get("DATA_DIR", "/data")
CONFIG_DIR = os.environ.get("CONFIG_DIR", "/config")

OPTIONS_PATH = os.path.join(DATA_DIR, "options.json")
MEDICATIONS_PATH = os.path.join(CONFIG_DIR, "medications.json")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")

_DEFAULTS = {
    "overdue_after_minutes": 60,
    "upcoming_lead_minutes": 30,
    "allow_take_early": True,
    "low_stock_days": 7,
    "history_days": 14,
    "publish_interval_seconds": 20,
    "log_level": "info",
}


def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return {}


@dataclass
class Settings:
    overdue_after_minutes: int = 60
    upcoming_lead_minutes: int = 30
    allow_take_early: bool = True
    low_stock_days: int = 7
    history_days: int = 14
    publish_interval_seconds: int = 20
    log_level: str = "info"

    # MQTT (from environment, injected by run.sh via bashio)
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_user: str = ""
    mqtt_password: str = ""


def load_settings() -> Settings:
    opts = {**_DEFAULTS, **_read_json(OPTIONS_PATH)}

    def _int(key):
        try:
            return int(opts.get(key))
        except (TypeError, ValueError):
            return _DEFAULTS[key]

    return Settings(
        overdue_after_minutes=_int("overdue_after_minutes"),
        upcoming_lead_minutes=_int("upcoming_lead_minutes"),
        allow_take_early=bool(opts.get("allow_take_early", True)),
        low_stock_days=_int("low_stock_days"),
        history_days=max(1, _int("history_days")),
        publish_interval_seconds=max(5, _int("publish_interval_seconds")),
        log_level=str(opts.get("log_level", "info")).lower(),
        mqtt_host=os.environ.get("MQTT_HOST", ""),
        mqtt_port=int(os.environ.get("MQTT_PORT", "1883") or 1883),
        mqtt_user=os.environ.get("MQTT_USER", ""),
        mqtt_password=os.environ.get("MQTT_PASSWORD", ""),
    )


def ensure_dirs() -> None:
    for d in (DATA_DIR, CONFIG_DIR):
        os.makedirs(d, exist_ok=True)
