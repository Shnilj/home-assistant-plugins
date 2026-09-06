"""MQTT publishing with Home Assistant device-based discovery.

Creates one HA **device per subject** (e.g. "MedTracker: Ellie") holding that
subject's medication entities and aggregate sensors, plus a **MedTracker hub**
device with the global sensors. Discovery messages and states are retained so
they survive a broker restart.

Per medication it exposes state / next-due / last-taken / counts, optional
inventory, and **Take / Skip / Undo** buttons whose command topics the add-on
subscribes to. Pressing a button (from the dashboard, an automation or a
notification action) drives the controller; the loop then republishes state.
"""
from __future__ import annotations

import json
import logging

import paho.mqtt.client as mqtt

from . import __version__

log = logging.getLogger("medtracker.mqtt")

DISCOVERY_PREFIX = "homeassistant"
BASE = "medtracker"
HUB_ID = "medtracker_hub"
STATUS_TOPIC = f"{BASE}/status"

MED_STATES = ["upcoming", "due", "overdue", "done", "none"]


def _sig_of(config: dict):
    """A structural signature: discovery only needs republishing when this
    changes (subjects/meds added/removed/renamed, unit or inventory toggled)."""
    out = []
    for s in config.get("subjects", []):
        out.append((
            s["id"], s["name"], s["kind"],
            tuple((m["id"], m["name"], m["unit"],
                   bool((m.get("inventory") or {}).get("track")),
                   bool(m.get("recurrence")))
                  for m in s.get("medications", [])),
        ))
    return tuple(out)


class MqttPublisher:
    def __init__(self, settings, controller):
        self.s = settings
        self.controller = controller
        self.connected = False
        self._sig = None
        self._last: dict[str, str] = {}   # topic -> last published payload (diff)
        self._sub_devices: set[str] = set()  # discovery device_ids we've published
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="medtracker")
        if settings.mqtt_user:
            self.client.username_pw_set(settings.mqtt_user, settings.mqtt_password)
        self.client.will_set(STATUS_TOPIC, "offline", retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

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
        client.subscribe([(f"{BASE}/+/cmd", 0), (f"{BASE}/+/+/cmd", 0)])
        client.publish(STATUS_TOPIC, "online", retain=True)
        # Force a full (re)publish of discovery + state on (re)connect.
        self._sig = None
        self._last.clear()
        self.publish(self.controller.model())

    def _on_disconnect(self, client, userdata, *args):
        self.connected = False
        log.warning("MQTT disconnected")

    # -- inbound commands ---------------------------------------------------
    def _on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8", "ignore").strip().upper()
            parts = msg.topic.split("/")
            # medtracker/<sid>/cmd            -> subject command
            # medtracker/<sid>/<mid>/cmd      -> medication command
            if len(parts) == 3 and parts[2] == "cmd":
                sid = parts[1]
                if payload in ("TAKE_ALL_DUE", "TAKE_ALL", "PRESS"):
                    n = self.controller.take_all_due(sid)
                    log.info("Command TAKE_ALL_DUE %s -> %d taken", sid, n)
            elif len(parts) == 4 and parts[3] == "cmd":
                sid, mid = parts[1], parts[2]
                if payload == "TAKE":
                    self.controller.take(sid, mid)
                elif payload == "SKIP":
                    self.controller.skip(sid, mid)
                elif payload == "UNDO":
                    self.controller.undo(sid, mid)
                else:
                    log.warning("Unknown med command %r on %s", payload, msg.topic)
        except Exception as exc:  # noqa: BLE001
            log.exception("Error handling command on %s: %s", msg.topic, exc)

    # -- discovery ----------------------------------------------------------
    def _hub_discovery(self):
        cmps = {
            "total_due": {
                "p": "sensor", "name": "Total due now", "icon": "mdi:pill-multiple",
                "state_topic": f"{BASE}/hub/total_due",
                "json_attributes_topic": f"{BASE}/hub/due_attrs",
                "unique_id": f"{HUB_ID}_total_due",
            },
            "overdue": {
                "p": "binary_sensor", "name": "Anyone overdue", "device_class": "problem",
                "state_topic": f"{BASE}/hub/overdue", "unique_id": f"{HUB_ID}_overdue",
            },
            "next_due": {
                "p": "sensor", "name": "Next due", "device_class": "timestamp",
                "state_topic": f"{BASE}/hub/next_due", "unique_id": f"{HUB_ID}_next_due",
            },
            "next_summary": {
                "p": "sensor", "name": "Next summary", "icon": "mdi:information-outline",
                "state_topic": f"{BASE}/hub/next_summary", "unique_id": f"{HUB_ID}_next_summary",
            },
        }
        return {
            "dev": {"ids": HUB_ID, "name": "MedTracker", "mf": "MedTracker",
                    "mdl": "Medication tracker", "sw": __version__},
            "o": {"name": "medtracker", "sw": __version__},
            "availability_topic": STATUS_TOPIC,
            "payload_available": "online", "payload_not_available": "offline",
            "cmps": cmps,
        }

    def _subject_discovery(self, subject):
        sid = subject["id"]
        dev_id = f"medtracker_{sid}"
        icon = {"animal": "mdi:paw", "person": "mdi:account", "other": "mdi:tag"}.get(
            subject["kind"], "mdi:account")
        cmps = {
            "due_now": {"p": "sensor", "name": "Due now", "icon": "mdi:pill",
                        "state_topic": f"{BASE}/{sid}/due_now", "unique_id": f"{dev_id}_due_now"},
            "remaining_today": {"p": "sensor", "name": "Remaining today", "icon": "mdi:clipboard-list",
                                "state_topic": f"{BASE}/{sid}/remaining_today",
                                "unique_id": f"{dev_id}_remaining_today"},
            "taken_today": {"p": "sensor", "name": "Taken today", "icon": "mdi:check-circle",
                            "state_topic": f"{BASE}/{sid}/taken_today",
                            "unique_id": f"{dev_id}_taken_today"},
            "overdue": {"p": "binary_sensor", "name": "Overdue", "device_class": "problem",
                        "state_topic": f"{BASE}/{sid}/overdue", "unique_id": f"{dev_id}_overdue"},
            "next_due": {"p": "sensor", "name": "Next due", "device_class": "timestamp",
                         "state_topic": f"{BASE}/{sid}/next_due", "unique_id": f"{dev_id}_next_due"},
            "next_med": {"p": "sensor", "name": "Next medication", "icon": "mdi:pill",
                         "state_topic": f"{BASE}/{sid}/next_med", "unique_id": f"{dev_id}_next_med"},
            "next_summary": {"p": "sensor", "name": "Next summary", "icon": "mdi:information-outline",
                             "state_topic": f"{BASE}/{sid}/next_summary",
                             "unique_id": f"{dev_id}_next_summary"},
            "take_all": {"p": "button", "name": "Take all due", "icon": "mdi:check-all",
                         "command_topic": f"{BASE}/{sid}/cmd", "payload_press": "TAKE_ALL_DUE",
                         "unique_id": f"{dev_id}_take_all"},
        }
        for med in subject.get("medications", []):
            cmps.update(self._med_components(sid, dev_id, med))

        return {
            "dev": {"ids": dev_id, "name": f"MedTracker: {subject['name']}",
                    "mf": "MedTracker", "mdl": subject["kind"].title(),
                    "sw": __version__, "via_device": HUB_ID},
            "o": {"name": "medtracker", "sw": __version__},
            "availability_topic": STATUS_TOPIC,
            "payload_available": "online", "payload_not_available": "offline",
            "cmps": cmps,
        }

    def _med_components(self, sid, dev_id, med):
        mid = med["id"]
        name = med["name"]
        unit = med["unit"]
        t = f"{BASE}/{sid}/{mid}"
        uid = f"{dev_id}_{mid}"
        cmd = f"{t}/cmd"
        cmps = {
            f"{mid}_state": {"p": "sensor", "name": f"{name} state", "icon": "mdi:pill",
                             "device_class": "enum", "options": MED_STATES,
                             "state_topic": f"{t}/state", "unique_id": f"{uid}_state"},
            f"{mid}_next_due": {"p": "sensor", "name": f"{name} next due", "device_class": "timestamp",
                                "state_topic": f"{t}/next_due", "unique_id": f"{uid}_next_due"},
            f"{mid}_last_taken": {"p": "sensor", "name": f"{name} last taken",
                                  "device_class": "timestamp", "state_topic": f"{t}/last_taken",
                                  "unique_id": f"{uid}_last_taken"},
            f"{mid}_taken_today": {"p": "sensor", "name": f"{name} taken today", "icon": "mdi:check-circle",
                                   "state_topic": f"{t}/taken_today", "unique_id": f"{uid}_taken_today"},
            f"{mid}_scheduled_today": {"p": "sensor", "name": f"{name} scheduled today",
                                       "icon": "mdi:calendar-check",
                                       "state_topic": f"{t}/scheduled_today",
                                       "unique_id": f"{uid}_scheduled_today"},
            f"{mid}_remaining_today": {"p": "sensor", "name": f"{name} remaining today",
                                       "icon": "mdi:clipboard-list",
                                       "state_topic": f"{t}/remaining", "unique_id": f"{uid}_remaining"},
            f"{mid}_dose_summary": {"p": "sensor", "name": f"{name} doses", "icon": "mdi:counter",
                                    "state_topic": f"{t}/dose_summary", "unique_id": f"{uid}_dose_summary"},
            f"{mid}_take": {"p": "button", "name": f"{name} take", "icon": "mdi:check",
                            "command_topic": cmd, "payload_press": "TAKE", "unique_id": f"{uid}_take"},
            f"{mid}_skip": {"p": "button", "name": f"{name} skip", "icon": "mdi:debug-step-over",
                            "command_topic": cmd, "payload_press": "SKIP", "unique_id": f"{uid}_skip"},
            f"{mid}_undo": {"p": "button", "name": f"{name} undo", "icon": "mdi:undo",
                            "command_topic": cmd, "payload_press": "UNDO", "unique_id": f"{uid}_undo"},
        }
        if (med.get("inventory") or {}).get("track"):
            cmps[f"{mid}_inventory"] = {
                "p": "sensor", "name": f"{name} inventory", "icon": "mdi:package-variant",
                "unit_of_measurement": unit, "state_topic": f"{t}/inv_remaining",
                "unique_id": f"{uid}_inventory"}
            cmps[f"{mid}_days_left"] = {
                "p": "sensor", "name": f"{name} days left", "icon": "mdi:calendar-clock",
                "unit_of_measurement": "d", "state_topic": f"{t}/inv_days_left",
                "unique_id": f"{uid}_days_left"}
            cmps[f"{mid}_low"] = {
                "p": "binary_sensor", "name": f"{name} low stock", "device_class": "problem",
                "state_topic": f"{t}/inv_low", "unique_id": f"{uid}_low"}
        if med.get("recurrence"):
            cmps[f"{mid}_course"] = {
                "p": "sensor", "name": f"{name} course", "icon": "mdi:calendar-repeat",
                "state_topic": f"{t}/course", "unique_id": f"{uid}_course"}
        return cmps

    def _publish_discovery(self, config):
        # Hub first, then a device per subject.
        self.client.publish(f"{DISCOVERY_PREFIX}/device/{HUB_ID}/config",
                            json.dumps(self._hub_discovery()), retain=True)
        live = {HUB_ID}
        for subject in config.get("subjects", []):
            dev_id = f"medtracker_{subject['id']}"
            live.add(dev_id)
            self.client.publish(f"{DISCOVERY_PREFIX}/device/{dev_id}/config",
                                json.dumps(self._subject_discovery(subject)), retain=True)
        # Remove discovery for devices (subjects) that no longer exist.
        for dev_id in self._sub_devices - live:
            self.client.publish(f"{DISCOVERY_PREFIX}/device/{dev_id}/config", "", retain=True)
        self._sub_devices = live
        log.info("Published MQTT discovery (%d subject device(s))", len(live) - 1)

    # -- state --------------------------------------------------------------
    def _pub(self, topic, payload):
        payload = "" if payload is None else str(payload)
        if self._last.get(topic) != payload:
            self.client.publish(topic, payload, retain=True)
            self._last[topic] = payload

    @staticmethod
    def _ts(iso):
        return iso if iso else "None"

    def publish(self, model):
        if not self.connected:
            return
        config = self.controller.get_config()
        sig = _sig_of(config)
        if sig != self._sig:
            self._publish_discovery(config)
            self._sig = sig

        hub = model["hub"]
        self._pub(f"{BASE}/hub/total_due", hub["total_due"])
        self._pub(f"{BASE}/hub/overdue", "ON" if hub["overdue"] else "OFF")
        self._pub(f"{BASE}/hub/next_due", self._ts(hub["next_due_iso"]))
        self._pub(f"{BASE}/hub/next_summary", hub["next_summary"])
        self._pub(f"{BASE}/hub/due_attrs", json.dumps({"due": hub["due_list"]}))

        for s in model["subjects"]:
            sid = s["id"]
            self._pub(f"{BASE}/{sid}/due_now", s["due_now"])
            self._pub(f"{BASE}/{sid}/remaining_today", s["remaining_today"])
            self._pub(f"{BASE}/{sid}/taken_today", s["taken_today"])
            self._pub(f"{BASE}/{sid}/overdue", "ON" if s["overdue"] else "OFF")
            self._pub(f"{BASE}/{sid}/next_due", self._ts(s["next_due_iso"]))
            self._pub(f"{BASE}/{sid}/next_med", s["next_med"])
            self._pub(f"{BASE}/{sid}/next_summary", s["next_summary"])
            for m in s["medications"]:
                mid = m["id"]
                t = f"{BASE}/{sid}/{mid}"
                self._pub(f"{t}/state", m["state"])
                self._pub(f"{t}/next_due", self._ts(m["next_due_iso"]))
                self._pub(f"{t}/last_taken", self._ts(m["last_taken_iso"]))
                self._pub(f"{t}/taken_today", m["taken_today"])
                self._pub(f"{t}/scheduled_today", m["scheduled_today"])
                self._pub(f"{t}/remaining", m["remaining_today"])
                self._pub(f"{t}/dose_summary", m["dose_summary"])
                if m.get("course"):
                    self._pub(f"{t}/course", m["course"]["summary"])
                inv = m["inventory"]
                if inv:
                    self._pub(f"{t}/inv_remaining", inv["remaining"])
                    self._pub(f"{t}/inv_days_left",
                              inv["days_left"] if inv["days_left"] is not None else "None")
                    self._pub(f"{t}/inv_low", "ON" if inv["low"] else "OFF")
