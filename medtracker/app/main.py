"""MedTracker orchestrator.

Owns the publish loop: recompute today's due doses, push changed values to MQTT,
prune history, then sleep until the next interval OR until a button press / web
action / external config edit wakes us early (via the controller's dirty flag).
The ingress web UI runs in a background thread.
"""
from __future__ import annotations

import logging
import threading

from . import config
from .controller import Controller
from .mqtt_client import MqttPublisher

log = logging.getLogger("medtracker")

_LEVELS = {
    "trace": logging.DEBUG, "debug": logging.DEBUG, "info": logging.INFO,
    "notice": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR,
    "fatal": logging.CRITICAL,
}


def main():
    settings = config.load_settings()
    logging.basicConfig(
        level=_LEVELS.get(settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config.ensure_dirs()

    controller = Controller(settings)
    mqtt = MqttPublisher(settings, controller)

    from .web.server import serve  # local import to avoid importing Flask at load
    threading.Thread(target=serve, args=(controller, settings), name="web", daemon=True).start()

    mqtt.start()
    log.info("MedTracker started (%d subject(s))", len(controller.subjects()))

    interval = settings.publish_interval_seconds
    try:
        while True:
            controller.dirty.clear()
            controller.reload_config_if_changed()
            try:
                mqtt.publish(controller.model())
                controller.prune()
            except Exception as exc:  # noqa: BLE001
                log.exception("Publish cycle failed: %s", exc)
            # Wake early on a button press / web action / config change.
            controller.dirty.wait(timeout=interval)
    except KeyboardInterrupt:
        pass
    finally:
        mqtt.stop()


if __name__ == "__main__":
    main()
