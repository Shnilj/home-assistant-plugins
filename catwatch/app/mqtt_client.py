"""MQTT publishing with Home Assistant device-based discovery.

Creates a single "CatWatch" device with:
  - Activity        (binary_sensor, motion)  — something is at the bowls
  - Current cat     (sensor)                  — who is there right now
  - Current zone    (sensor)                  — which bowl/fountain
  - Current action  (sensor)                  — eating / drinking / none
  - Snapshot        (image)                   — latest capture
  and, per cat:
  - <Cat> eating / drinking  (binary_sensor)
  - <Cat> last eaten / last drank  (sensor, timestamp)
  - <Cat> meals today / drinks today  (sensor)
"""
from __future__ import annotations

import json
import logging

import paho.mqtt.client as mqtt

from . import __version__, config

log = logging.getLogger("catwatch.mqtt")

DISCOVERY_PREFIX = "homeassistant"
DEVICE_ID = "catwatch"
BASE = "catwatch"
STATUS_TOPIC = f"{BASE}/status"
DISCOVERY_TOPIC = f"{DISCOVERY_PREFIX}/device/{DEVICE_ID}/config"
SNAPSHOT_TOPIC = f"{BASE}/snapshot"

# Per-action metadata: (state suffix, timestamp suffix, count suffix, duration suffix)
_ACTION = {
    "eating": ("eating", "last_eaten", "meals", "meal_duration"),
    "drinking": ("drinking", "last_drank", "drinks", "drink_duration"),
}


class MqttPublisher:
    def __init__(self, settings: config.Settings, on_state_change=None):
        self.s = settings
        self.connected = False
        self._on_state_change = on_state_change
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id="catwatch"
        )
        if settings.mqtt_user:
            self.client.username_pw_set(settings.mqtt_user, settings.mqtt_password)
        self.client.will_set(STATUS_TOPIC, "offline", retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

    # -- lifecycle ----------------------------------------------------------
    def start(self):
        if not self.s.mqtt_host:
            log.warning("No MQTT host configured; entities will not be published.")
            return
        try:
            self.client.connect_async(self.s.mqtt_host, self.s.mqtt_port, keepalive=60)
            self.client.loop_start()
        except Exception as exc:  # noqa: BLE001
            log.error("MQTT connect failed: %s", exc)

    def stop(self):
        try:
            self.client.publish(STATUS_TOPIC, "offline", retain=True)
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", False):
            log.error("MQTT connection failed: %s", reason_code)
            return
        self.connected = True
        log.info("MQTT connected")
        self.publish_discovery()
        client.publish(STATUS_TOPIC, "online", retain=True)
        if self._on_state_change:
            self._on_state_change(True)

    def _on_disconnect(self, client, userdata, *args):
        self.connected = False
        log.warning("MQTT disconnected")
        if self._on_state_change:
            self._on_state_change(False)

    # -- discovery ----------------------------------------------------------
    def _discovery_payload(self):
        cmps = {
            "activity": {
                "p": "binary_sensor",
                "name": "Activity",
                "device_class": "motion",
                "state_topic": f"{BASE}/activity",
                "unique_id": "catwatch_activity",
            },
            "current_cat": {
                "p": "sensor",
                "name": "Current cat",
                "icon": "mdi:cat",
                "state_topic": f"{BASE}/current_cat",
                "unique_id": "catwatch_current_cat",
            },
            "current_zone": {
                "p": "sensor",
                "name": "Current zone",
                "icon": "mdi:map-marker",
                "state_topic": f"{BASE}/current_zone",
                "unique_id": "catwatch_current_zone",
            },
            "current_action": {
                "p": "sensor",
                "name": "Current action",
                "icon": "mdi:silverware-fork-knife",
                "state_topic": f"{BASE}/current_action",
                "unique_id": "catwatch_current_action",
            },
            "snapshot": {
                "p": "image",
                "name": "Snapshot",
                "image_topic": SNAPSHOT_TOPIC,
                "content_type": "image/jpeg",
                "unique_id": "catwatch_snapshot",
            },
        }
        for slug, name in self.s.cat_slugs.items():
            cmps[f"{slug}_eating"] = {
                "p": "binary_sensor", "name": f"{name} eating", "icon": "mdi:cat",
                "state_topic": f"{BASE}/{slug}/eating", "unique_id": f"catwatch_{slug}_eating",
            }
            cmps[f"{slug}_drinking"] = {
                "p": "binary_sensor", "name": f"{name} drinking", "icon": "mdi:cup-water",
                "state_topic": f"{BASE}/{slug}/drinking", "unique_id": f"catwatch_{slug}_drinking",
            }
            cmps[f"{slug}_last_eaten"] = {
                "p": "sensor", "name": f"{name} last eaten", "device_class": "timestamp",
                "state_topic": f"{BASE}/{slug}/last_eaten", "unique_id": f"catwatch_{slug}_last_eaten",
            }
            cmps[f"{slug}_last_drank"] = {
                "p": "sensor", "name": f"{name} last drank", "device_class": "timestamp",
                "state_topic": f"{BASE}/{slug}/last_drank", "unique_id": f"catwatch_{slug}_last_drank",
            }
            cmps[f"{slug}_meals"] = {
                "p": "sensor", "name": f"{name} meals today", "icon": "mdi:bowl-mix",
                "state_class": "total", "state_topic": f"{BASE}/{slug}/meals",
                "unique_id": f"catwatch_{slug}_meals",
            }
            cmps[f"{slug}_drinks"] = {
                "p": "sensor", "name": f"{name} drinks today", "icon": "mdi:cup-water",
                "state_class": "total", "state_topic": f"{BASE}/{slug}/drinks",
                "unique_id": f"catwatch_{slug}_drinks",
            }
            cmps[f"{slug}_meal_duration"] = {
                "p": "sensor", "name": f"{name} last meal duration",
                "device_class": "duration", "unit_of_measurement": "s",
                "state_class": "measurement", "icon": "mdi:timer-outline",
                "state_topic": f"{BASE}/{slug}/meal_duration",
                "unique_id": f"catwatch_{slug}_meal_duration",
            }
            cmps[f"{slug}_drink_duration"] = {
                "p": "sensor", "name": f"{name} last drink duration",
                "device_class": "duration", "unit_of_measurement": "s",
                "state_class": "measurement", "icon": "mdi:timer-outline",
                "state_topic": f"{BASE}/{slug}/drink_duration",
                "unique_id": f"catwatch_{slug}_drink_duration",
            }
            cmps[f"{slug}_overdue"] = {
                "p": "binary_sensor", "name": f"{name} overdue", "device_class": "problem",
                "icon": "mdi:alert", "state_topic": f"{BASE}/{slug}/overdue",
                "unique_id": f"catwatch_{slug}_overdue",
            }
            cmps[f"{slug}_meals_week"] = {
                "p": "sensor", "name": f"{name} meals this week", "icon": "mdi:calendar-week",
                "state_class": "total", "state_topic": f"{BASE}/{slug}/meals_week",
                "unique_id": f"catwatch_{slug}_meals_week",
            }
            cmps[f"{slug}_eating_minutes_week"] = {
                "p": "sensor", "name": f"{name} eating minutes this week",
                "device_class": "duration", "unit_of_measurement": "min",
                "state_class": "total", "icon": "mdi:timer-sand",
                "state_topic": f"{BASE}/{slug}/eating_minutes_week",
                "unique_id": f"catwatch_{slug}_eating_minutes_week",
            }

        return {
            "dev": {
                "ids": DEVICE_ID, "name": "CatWatch", "mf": "CatWatch",
                "mdl": "Local cat recognition", "sw": __version__,
            },
            "o": {"name": "catwatch", "sw": __version__},
            "availability_topic": STATUS_TOPIC,
            "payload_available": "online",
            "payload_not_available": "offline",
            "cmps": cmps,
        }

    def publish_discovery(self):
        self.client.publish(
            DISCOVERY_TOPIC, json.dumps(self._discovery_payload()), retain=True
        )
        log.info("Published MQTT discovery for %d cats", len(self.s.cats))

    # -- state --------------------------------------------------------------
    def pub(self, topic, payload, retain=True):
        if payload is None:
            return
        self.client.publish(topic, payload, retain=retain)

    def publish_activity(self, active: bool):
        self.pub(f"{BASE}/activity", "ON" if active else "OFF")

    def publish_current_cat(self, name: str):
        self.pub(f"{BASE}/current_cat", name or "none")

    def publish_current_zone(self, name: str):
        self.pub(f"{BASE}/current_zone", name or "none")

    def publish_current_action(self, action: str):
        self.pub(f"{BASE}/current_action", action or "none")

    def publish_action_state(self, slug: str, action: str, active: bool):
        key = _ACTION[action][0]
        self.pub(f"{BASE}/{slug}/{key}", "ON" if active else "OFF")

    def publish_action_timestamp(self, slug: str, action: str, iso_ts: str):
        key = _ACTION[action][1]
        self.pub(f"{BASE}/{slug}/{key}", iso_ts)

    def publish_action_count(self, slug: str, action: str, count: int):
        key = _ACTION[action][2]
        self.pub(f"{BASE}/{slug}/{key}", str(count))

    def publish_action_duration(self, slug: str, action: str, seconds: int):
        key = _ACTION[action][3]
        self.pub(f"{BASE}/{slug}/{key}", str(seconds))

    def publish_overdue(self, slug: str, overdue: bool):
        self.pub(f"{BASE}/{slug}/overdue", "ON" if overdue else "OFF")

    def publish_meals_week(self, slug: str, meals: int):
        self.pub(f"{BASE}/{slug}/meals_week", str(meals))

    def publish_eating_minutes_week(self, slug: str, minutes: int):
        self.pub(f"{BASE}/{slug}/eating_minutes_week", str(minutes))

    def publish_snapshot(self, jpg_bytes: bytes):
        if jpg_bytes:
            self.client.publish(SNAPSHOT_TOPIC, jpg_bytes, retain=True)
