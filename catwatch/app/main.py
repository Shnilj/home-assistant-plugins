"""CatWatch orchestrator.

Runs the capture + motion + recognition loop in the main thread and the ingress
web UI in a background thread.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime

import cv2

from . import classifier, config
from .capture import RtspCamera
from .motion import MotionDetector, clamp_roi
from .mqtt_client import MqttPublisher
from .state import ModelHolder, SharedState

log = logging.getLogger("catwatch")

_LEVELS = {
    "trace": logging.DEBUG,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "notice": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "fatal": logging.CRITICAL,
}


def _encode_jpg(img, quality: int) -> bytes | None:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    return buf.tobytes() if ok else None


def _crop(frame, bbox, roi, pad=0.15):
    """Crop the cat region: prefer the motion bbox, fall back to the ROI."""
    h, w = frame.shape[:2]
    if bbox is not None:
        x, y, bw, bh = bbox
        px, py = int(bw * pad), int(bh * pad)
        x0, y0 = max(0, x - px), max(0, y - py)
        x1, y1 = min(w, x + bw + px), min(h, y + bh + py)
    elif roi is not None:
        x0, y0, rw, rh = roi
        x1, y1 = x0 + rw, y0 + rh
    else:
        return frame
    if x1 - x0 < 8 or y1 - y0 < 8:
        return frame
    return frame[y0:y1, x0:x1]


def _annotate(frame, bbox, label, conf):
    img = frame.copy()
    if bbox is not None:
        x, y, w, h = bbox
        cv2.rectangle(img, (x, y), (x + w, y + h), (0, 200, 0), 2)
    text = f"{label} {conf:.2f}" if label != "none" else "none"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cv2.putText(img, text, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 0), 2)
    cv2.putText(img, stamp, (10, img.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (255, 255, 255), 1)
    return img


class CatWatch:
    def __init__(self, settings: config.Settings):
        self.s = settings
        self.state = SharedState(settings.cats)
        self.camera = RtspCamera(settings.rtsp_url)
        self.motion = MotionDetector(settings.motion_sensitivity, settings.motion_min_area)
        self.model_holder = ModelHolder(classifier.SignatureModel.load())
        self.mqtt = MqttPublisher(
            settings,
            on_state_change=lambda c: self.state.update_status(mqtt_connected=c),
        )
        # presence state machine
        self._present_since = None
        self._absent_since = None
        self._active_label = "unknown"
        self._eating_registered = False
        self._eating_cat = None
        self._capture_saved = False
        # When each cat's last meal was counted (for the cooldown debounce).
        self._last_meal_ts = {name: None for name in settings.cats}
        self._roi = None
        self._roi_reloaded = 0.0
        self._last_ui_frame = 0.0
        self._today = datetime.now().date()

    # -- helpers ------------------------------------------------------------
    def _reload_roi(self):
        now = time.time()
        if now - self._roi_reloaded > 2.0:
            self._roi = config.load_roi()
            self._roi_reloaded = now

    def _maybe_reset_daily(self):
        today = datetime.now().date()
        if today != self._today:
            self._today = today
            for name in self.s.cats:
                self.state.update_cat(name, meals_today=0)
                self.mqtt.publish_cat_meals(config.slugify(name), 0)
                self._last_meal_ts[name] = None
            log.info("Daily meal counters reset")

    def _start_eating(self, name, frame, bbox, conf, now):
        """Mark a cat as eating. Counts a *new* meal only if enough time has
        passed since this cat's last one (cooldown), so a single feeding window
        — even when split into flickers by the motion detector — is one meal."""
        slug = config.slugify(name)
        ts = datetime.now().astimezone()
        cooldown = self.s.meal_cooldown_minutes * 60
        last = self._last_meal_ts.get(name)
        new_meal = last is None or (now - last) >= cooldown

        if new_meal:
            meals = self.state.cats[name]["meals_today"] + 1
            self.state.update_cat(name, meals_today=meals)
            self.mqtt.publish_cat_meals(slug, meals)
            log.info("%s — new meal #%d (conf %.2f)", name, meals, conf)
        else:
            log.debug("%s still in the same meal window (conf %.2f)", name, conf)
        self._last_meal_ts[name] = now

        self.state.update_cat(name, eating=True, last_eaten=ts.isoformat())
        self.mqtt.publish_cat_eating(slug, True)
        self.mqtt.publish_cat_last_eaten(slug, ts.isoformat())

        annotated = _annotate(frame, bbox, name, conf)
        jpg = _encode_jpg(annotated, self.s.jpeg_quality)
        if jpg:
            self.state.set_snapshot(jpg)
            self.mqtt.publish_snapshot(jpg)
            # Only keep a snapshot file on disk for an actual new meal, not for
            # every flicker within the same feeding window.
            if new_meal:
                fname = f"{slug}_{ts.strftime('%Y%m%d_%H%M%S')}.jpg"
                try:
                    with open(os.path.join(config.SNAP_DIR, fname), "wb") as fh:
                        fh.write(jpg)
                except OSError as exc:
                    log.warning("Could not write snapshot: %s", exc)

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

    def _end_presence(self):
        if self._present_since is None:
            return
        self.state.update_status(activity=False, current_cat="none", current_confidence=0.0)
        self.mqtt.publish_activity(False)
        self.mqtt.publish_current_cat("none")
        if self._eating_cat:
            self.state.update_cat(self._eating_cat, eating=False)
            self.mqtt.publish_cat_eating(config.slugify(self._eating_cat), False)
        self._present_since = None
        self._absent_since = None
        self._active_label = "unknown"
        self._eating_registered = False
        self._eating_cat = None
        self._capture_saved = False

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
            elapsed = time.time() - loop_start
            time.sleep(max(0.0, interval - elapsed))

    def _tick(self):
        self._maybe_reset_daily()
        frame = self.camera.read()
        self.state.update_status(
            camera_connected=self.camera.connected,
            model_ready=self.model_holder.get().ready,
        )
        if frame is None:
            self._end_presence()
            return

        # Keep a recent frame available to the ROI editor (throttled).
        now = time.time()
        if now - self._last_ui_frame > 0.5:
            jpg = _encode_jpg(frame, self.s.jpeg_quality)
            if jpg:
                self.state.set_frame(jpg)
            self._last_ui_frame = now

        self._reload_roi()
        motion, area, bbox = self.motion.process(frame, self._roi)

        if not motion:
            # Don't end the presence on the first still frame — a cat holding
            # still gets absorbed into the background and motion flickers off.
            # Only end after motion has been absent for the grace period.
            if self._present_since is not None:
                if self._absent_since is None:
                    self._absent_since = now
                elif (now - self._absent_since) >= self.s.presence_grace_seconds:
                    self._end_presence()
            return

        # Motion present: cancel any pending "absent" timer.
        self._absent_since = None

        crop = _crop(frame, bbox, clamp_roi(self._roi, frame.shape))
        model = self.model_holder.get()
        label, conf = model.predict(crop)
        display = label if (conf >= self.s.classifier_confidence and label != "unknown") else "unknown"

        self.state.update_status(activity=True, current_cat=display, current_confidence=conf)
        self.mqtt.publish_activity(True)
        self.mqtt.publish_current_cat(display)

        if self._present_since is None:
            self._present_since = now
        self._active_label = display

        dwell_ok = (now - self._present_since) >= self.s.eating_dwell_seconds

        # Gather a training capture shortly after a cat settles in.
        if not self._capture_saved and (now - self._present_since) >= min(
            1.0, self.s.eating_dwell_seconds
        ):
            self._save_capture(crop, display, conf)
            self._capture_saved = True

        if dwell_ok and not self._eating_registered and display != "unknown":
            self._start_eating(display, frame, bbox, conf, now)
            self._eating_registered = True
            self._eating_cat = display


def main():
    settings = config.load_settings()
    logging.basicConfig(
        level=_LEVELS.get(settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config.ensure_dirs(settings)
    log.info("CatWatch starting (cats: %s)", ", ".join(settings.cats) or "none")

    app = CatWatch(settings)

    # Web UI (ingress) in a background thread.
    from .web.server import serve  # local import to avoid import cost if unused

    threading.Thread(
        target=serve, args=(app.state, settings, app.model_holder, app.camera),
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
