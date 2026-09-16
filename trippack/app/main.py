"""TripPack entry point.

Reads the add-on options, builds the controller, serves the web UI. The MQTT
publisher is deliberately absent for now — `controller.dirty` and
`controller.summary()` are the two hooks it will need when it arrives.
"""

from __future__ import annotations

import json
import logging
import os
import sys

from .controller import Controller
from .web import server

OPTIONS_PATH = "/data/options.json"
DEFAULTS = {"log_level": "info", "data_file": "/config/trippack.json"}


def load_options(path=OPTIONS_PATH):
    options = dict(DEFAULTS)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            options.update({k: v for k, v in json.load(handle).items() if v not in (None, "")})
    except (OSError, ValueError):
        pass
    return options


def setup_logging(level):
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def main():
    options = load_options()
    setup_logging(os.environ.get("LOG_LEVEL") or options["log_level"])
    log = logging.getLogger("trippack")

    data_file = options["data_file"]
    controller = Controller(path=data_file)
    log.info(
        "TripPack ready: %d items, %d trips, data in %s",
        len(controller.catalog),
        len(controller.state().get("trips") or []),
        data_file,
    )
    server.serve(controller, port=int(os.environ.get("PORT", "8097")))


if __name__ == "__main__":
    main()
