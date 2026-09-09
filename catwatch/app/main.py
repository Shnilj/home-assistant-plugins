"""CatWatch orchestrator.

Runs the capture + motion + recognition loop in the main thread and the ingress
web UI in a background thread.

A cat is recognised from the motion crop; whichever zone it covers (and leans
into) decides the action — eating over a food zone, drinking over a water zone.
Dwell time gates the action; a per-cat, per-action cooldown gates the count.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime

import cv2

from . import classifier, config, zones
from .capture import RtspCamera
from .history import EventLog
from .motion import MotionDetector
from .mqtt_client import MqttPublisher
from .state import ModelHolder, SharedState
from .stats import DailyStats

log = logging.getLogger("catwatch")

_LEVELS = {
    "trace": logging.DEBUG, "debug": logging.DEBUG, "info": logging.INFO,
    "notice": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR,
    "fatal": logging.CRITICAL,
}

# action -> (SharedState eating/drinking key, timestamp key, count key)
_ACTION_KEYS = {
    "eating": ("eating", "last_eaten", "meals_today"),
    "drinking": ("drinking", "last_drank", "drinks_today"),
}


def _encode_jpg(img, quality: int) -> bytes | None:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    return buf.tobytes() if ok else None


def _crop(frame, bbox, pad=0.15):
    """Crop the cat region from the motion bounding box (with padding)."""
    if bbox is None:
        return frame
    h, w = frame.shape[:2]
    x, y, bw, bh = bbox
    px, py = int(bw * pad), int(bh * pad)
    x0, y0 = max(0, x - px), max(0, y - py)
    x1, y1 = min(w, x + bw + px), min(h, y + bh + py)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return frame
    return frame[y0:y1, x0:x1]


def _vote_winner(votes):
    """Return (label, winning_share 0-1) from accumulated vote weights."""
    if not votes:
        return None, 0.0
    total = sum(votes.values()) + 1e-6
    winner = max(votes, key=votes.get)
    return winner, votes[winner] / total


def _iso_epoch(iso_ts):
    try:
        return datetime.fromisoformat(iso_ts).timestamp()
    except (ValueError, TypeError):
        return None


def _annotate(frame, bbox, caption):
    img = frame.copy()
    if bbox is not None:
        x, y, w, h = bbox
        cv2.rectangle(img, (x, y), (x + w, y + h), (0, 200, 0), 2)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cv2.putText(img, caption, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 0), 2)
    cv2.putText(img, stamp, (10, img.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (255, 255, 255), 1)
    return img


class CatWatch:
    def __init__(self, settings: config.Settings):
        self.s = settings
        self.state = SharedState(settings.cats)
        self.camera = RtspCamera(settings.rtsp_url)
        self.motion = MotionDetector(settings.motion_sensitivity, settings.motion_min_area)
        classifier.init_recognizer(settings)
        self.model_holder = ModelHolder(classifier.SignatureModel.load())
        self.mqtt = MqttPublisher(
            settings,
            on_state_change=lambda c: self.state.update_status(mqtt_connected=c),
        )
        # activity (any motion at the feeding area)
        self._activity_on = False
        self._activity_since = None
        self._absent_since = None
        self._capture_saved = False
        # interaction (a cat using a specific zone)
        self._interaction = None
        self._last_action_ts = {n: {"eating": None, "drinking": None} for n in settings.cats}
        # zones
        self._zones = []
        self._zones_reloaded = 0.0
        self._last_ui_frame = 0.0
        self._today = datetime.now().date()
        # event history (rolling archive of counted events)
        self.history = EventLog(config.EVENTS_PATH, config.SNAP_DIR, crop_dir=config.EVENT_CROP_DIR)
        self.history.prune(self.s.history_hours * 3600)
        self._last_prune = time.time()
        # durable daily aggregate (weekly summaries, overdue, counters)
        self.stats = DailyStats(config.STATS_PATH)
        self.stats.prune()
        self._last_eaten_epoch = {n: None for n in settings.cats}
        self._seed_last_eaten()
        self._overdue_state = {n: None for n in settings.cats}
        self._last_overdue_check = 0.0
        self._initial_published = False
        # daily counters are derived from the durable stats store, so they survive
        # a restart and reflect corrections/deletes made from the web UI.
        self._last_stats_version = -1
        for n in settings.cats:
            tc = self.stats.today_counts(n)
            self.state.update_cat(n, meals_today=tc["eating"], drinks_today=tc["drinking"])

    # -- helpers ------------------------------------------------------------
    def _reload_zones(self):
        now = time.time()
        if now - self._zones_reloaded > 2.0:
            self._zones = config.load_zones()
            self._zones_reloaded = now

    def _maybe_reset_daily(self):
        today = datetime.now().date()
        if today != self._today:
            self._today = today
            self.stats.prune()
            for name in self.s.cats:
                self.state.update_cat(name, meals_today=0, drinks_today=0)
                slug = config.slugify(name)
                self.mqtt.publish_action_count(slug, "eating", 0)
                self.mqtt.publish_action_count(slug, "drinking", 0)
                self._last_action_ts[name] = {"eating": None, "drinking": None}
                self._publish_weekly(name)
            log.info("Daily counters reset")

    def _seed_last_eaten(self):
        """On startup, seed each cat's last-eaten time from the recent history so
        the overdue check works without waiting for the next meal."""
        for e in self.history.list():
            cat = e.get("cat")
            if (e.get("action") == "eating" and cat in self._last_eaten_epoch
                    and self._last_eaten_epoch[cat] is None):
                ep = _iso_epoch(e.get("ts"))
                if ep:
                    self._last_eaten_epoch[cat] = ep

    def _publish_weekly(self, cat):
        w = self.stats.week_totals(cat)
        slug = config.slugify(cat)
        self.mqtt.publish_meals_week(slug, w["meals"])
        self.mqtt.publish_eating_minutes_week(slug, round(w["eat_sec"] / 60))

    def _update_overdue(self, now):
        if now - self._last_overdue_check < 30:
            return
        self._last_overdue_check = now
        if self.s.overdue_hours <= 0:
            return
        threshold = self.s.overdue_hours * 3600
        for cat in self.s.cats:
            le = self._last_eaten_epoch.get(cat)
            overdue = le is not None and (now - le) > threshold
            if overdue != self._overdue_state.get(cat):
                self._overdue_state[cat] = overdue
                self.state.update_cat(cat, overdue=overdue)
                self.mqtt.publish_overdue(config.slugify(cat), overdue)

    def _publish_initial(self, now):
        for cat in self.s.cats:
            le = self._last_eaten_epoch.get(cat)
            overdue = (self.s.overdue_hours > 0 and le is not None
                       and (now - le) > self.s.overdue_hours * 3600)
            self._overdue_state[cat] = overdue
            self.state.update_cat(cat, overdue=overdue)
            self.mqtt.publish_overdue(config.slugify(cat), overdue)

    def _sync_counts(self):
        """Republish daily counts + weekly totals whenever the stats store changes
        (our own events, or a correction/delete from the web UI)."""
        if not self.mqtt.connected or self.stats.version == self._last_stats_version:
            return
        self._last_stats_version = self.stats.version
        for cat in self.s.cats:
            slug = config.slugify(cat)
            meals = self.stats.count(cat, "eating")
            drinks = self.stats.count(cat, "drinking")
            self.state.update_cat(cat, meals_today=meals, drinks_today=drinks)
            self.mqtt.publish_action_count(slug, "eating", meals)
            self.mqtt.publish_action_count(slug, "drinking", drinks)
            self._publish_weekly(cat)

    def _set_activity(self, on, now, cat="none", conf=0.0):
        if on:
            if not self._activity_on:
                self._activity_on = True
                self._activity_since = now
                self._capture_saved = False
                self.mqtt.publish_activity(True)
            self.state.update_status(activity=True, current_cat=cat, current_confidence=conf)
            self.mqtt.publish_current_cat(cat)
        else:
            if self._activity_on:
                self._activity_on = False
                self.mqtt.publish_activity(False)
                self.mqtt.publish_current_cat("none")
                self.mqtt.publish_current_zone("none")
                self.mqtt.publish_current_action("none")
            self.state.update_status(
                activity=False, current_cat="none", current_confidence=0.0,
                current_zone="none", current_action="none", current_elapsed=0,
            )
            self._absent_since = None
            self._activity_since = None

    def _publish_current(self, zone_name, action):
        self.state.update_status(current_zone=zone_name, current_action=action)
        self.mqtt.publish_current_zone(zone_name)
        self.mqtt.publish_current_action(action)

    def _save_capture(self, crop, guessed, conf):
        if not self.s.save_captures or crop is None or crop.size == 0:
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"{ts}_{config.slugify(guessed)}_{int(conf * 100):02d}.jpg"
        jpg = _encode_jpg(crop, self.s.jpeg_quality)
        if jpg:
            try:
                with open(os.path.join(config.UNLABELED_DIR, fname), "wb") as fh:
                    fh.write(jpg)
            except OSError as exc:
                log.warning("Could not write capture: %s", exc)

    def _register_action(self, action, cat, frame, bbox, conf, now, zone):
        """Turn on the eating/drinking sensor and count a new event only if the
        cooldown for this cat+action has elapsed (so one feeding/drinking window
        counts once, even when the motion flickers)."""
        slug = config.slugify(cat)
        ts = datetime.now().astimezone()
        state_key, ts_key, count_key = _ACTION_KEYS[action]
        cooldown = self.s.cooldown_for(action) * 60
        last = self._last_action_ts[cat][action]
        new_event = last is None or (now - last) >= cooldown
        if action == "eating":
            self._last_eaten_epoch[cat] = now

        if new_event:
            self.stats.add_event(cat, action)  # counts + weekly republished by _sync_counts
            log.info("%s — %s at %s (#%d, conf %.2f)", cat, action, zone["name"],
                     self.stats.count(cat, action), conf)
        self._last_action_ts[cat][action] = now

        self.state.update_cat(cat, **{state_key: True, ts_key: ts.isoformat()})
        self.mqtt.publish_action_state(slug, action, True)
        self.mqtt.publish_action_timestamp(slug, action, ts.isoformat())

        verb = "eating" if action == "eating" else "drinking"
        annotated = _annotate(frame, bbox, f"{cat} {verb} - {zone['name']}")
        jpg = _encode_jpg(annotated, self.s.jpeg_quality)
        fname = None
        if jpg:
            self.state.set_snapshot(jpg)
            self.mqtt.publish_snapshot(jpg)
            if new_event:
                fname = f"{slug}_{action}_{ts.strftime('%Y%m%d_%H%M%S')}.jpg"
                try:
                    with open(os.path.join(config.SNAP_DIR, fname), "wb") as fh:
                        fh.write(jpg)
                except OSError as exc:
                    log.warning("Could not write snapshot: %s", exc)
                    fname = None

        if new_event:
            # Also save the raw (unannotated) cat crop, so a later correction can
            # file it as a clean training example for the right cat.
            crop_name = None
            cjpg = _encode_jpg(_crop(frame, bbox), self.s.jpeg_quality)
            if cjpg is not None:
                crop_name = f"crop_{slug}_{ts.strftime('%Y%m%d_%H%M%S')}.jpg"
                try:
                    with open(os.path.join(config.EVENT_CROP_DIR, crop_name), "wb") as fh:
                        fh.write(cjpg)
                except OSError as exc:
                    log.warning("Could not write event crop: %s", exc)
                    crop_name = None
            eid = self.history.add(cat, action, zone["name"], fname, ts.isoformat(), crop=crop_name)
            self.history.prune(self.s.history_hours * 3600)
            return eid
        return None

    def _update_interaction(self, zone, action, display, conf, frame, bbox, now):
        """One interaction per (zone, action). Recognition votes accumulate over
        the whole visit — a per-frame misread doesn't restart the visit or decide
        the cat; the majority winner does, and only if it clears the margin."""
        I = self._interaction
        if I is None or I["zone_id"] != zone["id"] or I["action"] != action:
            self._end_interaction()
            I = self._interaction = {
                "zone_id": zone["id"], "zone_name": zone["name"], "action": action,
                "since": now, "last_seen": now, "counted": False, "reached_dwell": False,
                "counted_cat": None, "event_id": None, "votes": {},
                "last_frame": None, "last_bbox": None,
                "best_conf": -1.0, "best_frame": None, "best_bbox": None,
            }
        else:
            I["last_seen"] = now
        I["last_frame"], I["last_bbox"] = frame, bbox
        # Remember the clearest frame of the visit (highest recognition confidence).
        # A grey/glitchy frame scores low, so it is never chosen as the snapshot.
        if conf > I["best_conf"]:
            I["best_conf"], I["best_frame"], I["best_bbox"] = conf, frame, bbox

        if display != "unknown":
            I["votes"][display] = I["votes"].get(display, 0.0) + max(conf, 0.0)

        if (now - I["since"]) >= self.s.dwell_for(action):
            I["reached_dwell"] = True

        winner, share = _vote_winner(I["votes"])
        if (not I["counted"] and I["reached_dwell"]
                and winner is not None and share >= self.s.recognition_margin):
            I["event_id"] = self._register_action(action, winner, frame, bbox, share, now, zone)
            I["counted"] = True
            I["counted_cat"] = winner

    def _end_interaction(self):
        I = self._interaction
        if I and I.get("counted") and I.get("counted_cat"):
            cat, action = I["counted_cat"], I["action"]
            slug = config.slugify(cat)
            state_key = _ACTION_KEYS[action][0]
            self.state.update_cat(cat, **{state_key: False})
            self.mqtt.publish_action_state(slug, action, False)

            # visit duration = arrival to last time the cat was seen at the zone
            duration = int(round(max(0.0, I["last_seen"] - I["since"])))
            dur_key = "last_meal_duration" if action == "eating" else "last_drink_duration"
            self.state.update_cat(cat, **{dur_key: duration})
            self.mqtt.publish_action_duration(slug, action, duration)
            self.stats.add_duration(cat, action, duration)  # weekly republished by _sync_counts
            if I.get("event_id"):
                self.history.set_duration(I["event_id"], duration)
                self._finalize_snapshot(I, cat)
        elif (I and self.s.log_unknown_visits and I.get("reached_dwell")
              and not I.get("counted")):
            # a real visit the recogniser couldn't attribute — log it so it can
            # be labelled from the timeline (the hard cases the model needs)
            self._log_unknown(I)
        self._interaction = None

    def _finalize_snapshot(self, I, cat):
        """Rewrite the event's snapshot + training crop from the clearest frame of
        the visit, so the history thumbnail reliably shows the cat rather than a
        single unlucky commit-instant (or glitchy) frame."""
        frame, bbox = I.get("best_frame"), I.get("best_bbox")
        if frame is None:
            return
        ev = self.history.get(I["event_id"])
        if not ev:
            return
        verb = "eating" if I["action"] == "eating" else "drinking"
        jpg = _encode_jpg(_annotate(frame, bbox, f"{cat} {verb} - {I['zone_name']}"),
                          self.s.jpeg_quality)
        if jpg:
            self.state.set_snapshot(jpg)
            self.mqtt.publish_snapshot(jpg)
            sname = ev.get("snapshot")
            if sname:
                try:
                    with open(os.path.join(config.SNAP_DIR, os.path.basename(sname)), "wb") as fh:
                        fh.write(jpg)
                except OSError:
                    pass
        cjpg = _encode_jpg(_crop(frame, bbox), self.s.jpeg_quality)
        cname = ev.get("crop")
        if cjpg is not None and cname:
            try:
                with open(os.path.join(config.EVENT_CROP_DIR, os.path.basename(cname)), "wb") as fh:
                    fh.write(cjpg)
            except OSError:
                pass

    def _log_unknown(self, I):
        frame, bbox = I.get("best_frame"), I.get("best_bbox")
        if frame is None:
            frame, bbox = I.get("last_frame"), I.get("last_bbox")
        if frame is None:
            return
        ts = datetime.now().astimezone()
        action, zone_name = I["action"], I["zone_name"]
        verb = "eating" if action == "eating" else "drinking"
        stamp = ts.strftime("%Y%m%d_%H%M%S")

        fname = None
        jpg = _encode_jpg(_annotate(frame, bbox, f"unknown {verb} - {zone_name}"), self.s.jpeg_quality)
        if jpg:
            fname = f"unknown_{action}_{stamp}.jpg"
            try:
                with open(os.path.join(config.SNAP_DIR, fname), "wb") as fh:
                    fh.write(jpg)
            except OSError:
                fname = None

        crop_name = None
        cjpg = _encode_jpg(_crop(frame, bbox), self.s.jpeg_quality)
        if cjpg is not None:
            crop_name = f"crop_unknown_{action}_{stamp}.jpg"
            try:
                with open(os.path.join(config.EVENT_CROP_DIR, crop_name), "wb") as fh:
                    fh.write(cjpg)
            except OSError:
                crop_name = None

        eid = self.history.add("unknown", action, zone_name, fname, ts.isoformat(), crop=crop_name)
        self.history.set_duration(eid, int(round(max(0.0, I["last_seen"] - I["since"]))))
        self.history.prune(self.s.history_hours * 3600)
        log.info("Unknown %s at %s logged for labelling", verb, zone_name)

    def _expire_interaction(self, now):
        I = self._interaction
        if I and (now - I["last_seen"]) >= self.s.presence_grace_seconds:
            self._end_interaction()

    def _clear(self):
        self._set_activity(False, time.time())
        self._end_interaction()

    # -- main loop ----------------------------------------------------------
    def run(self):
        self.camera.start()
        self.mqtt.start()
        interval = 1.0 / max(1, self.s.detection_fps)
        log.info("Processing loop started at %d fps", self.s.detection_fps)
        while True:
            loop_start = time.time()
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001
                log.exception("Error in processing loop: %s", exc)
            time.sleep(max(0.0, interval - (time.time() - loop_start)))

    def _tick(self):
        self.state.set_heartbeat(time.time())  # liveness for the watchdog
        self._maybe_reset_daily()
        frame = self.camera.read()
        self.state.update_status(
            camera_connected=self.camera.connected,
            model_ready=self.model_holder.get().ready,
        )
        if frame is None:
            self._clear()
            return

        now = time.time()
        if now - self._last_ui_frame > 0.5:
            jpg = _encode_jpg(frame, self.s.jpeg_quality)
            if jpg:
                self.state.set_frame(jpg)
            self._last_ui_frame = now

        if now - self._last_prune > 600:
            self.history.prune(self.s.history_hours * 3600)
            self._last_prune = now

        if self.mqtt.connected and not self._initial_published:
            self._publish_initial(now)
            self._initial_published = True
        self._update_overdue(now)
        self._sync_counts()

        self._reload_zones()
        region = zones.detect_region(self._zones, frame.shape)
        motion, area, bbox = self.motion.process(frame, region)

        if not motion or bbox is None:
            # Debounce: a still cat blends into the background and flickers off.
            if self._activity_on:
                if self._absent_since is None:
                    self._absent_since = now
                elif (now - self._absent_since) >= self.s.presence_grace_seconds:
                    self._set_activity(False, now)
            self._expire_interaction(now)
            return

        self._absent_since = None
        crop = _crop(frame, bbox)
        label, conf = self.model_holder.get().predict(crop)
        display = label if (conf >= self.s.classifier_confidence and label != "unknown") else "unknown"
        self._set_activity(True, now, display, conf)

        if not self._capture_saved and self._activity_since and (now - self._activity_since) >= 1.0:
            self._save_capture(crop, display, conf)
            self._capture_saved = True

        best, _cov = zones.pick_zone(bbox, self._zones, self.s)
        if best is not None:
            action = "eating" if best["type"] == "food" else "drinking"
            self._update_interaction(best, action, display, conf, frame, bbox, now)
            I = self._interaction
            if I and I["counted"]:
                self.state.update_status(current_elapsed=int(now - I["since"]))
                self._publish_current(best["name"], action)
            else:
                self.state.update_status(current_elapsed=0)
                self._publish_current(best["name"], f"approaching {action}")
        else:
            self.state.update_status(current_elapsed=0)
            self._publish_current("none", "none")

        self._expire_interaction(now)


def main():
    settings = config.load_settings()
    logging.basicConfig(
        level=_LEVELS.get(settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config.ensure_dirs(settings)
    log.info("CatWatch starting (cats: %s)", ", ".join(settings.cats) or "none")

    app = CatWatch(settings)

    from .web.server import serve  # local import
    threading.Thread(
        target=serve,
        args=(app.state, settings, app.model_holder, app.history, app.stats, app.camera),
        name="web", daemon=True,
    ).start()

    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        app.mqtt.stop()
        app.camera.stop()


if __name__ == "__main__":
    main()
