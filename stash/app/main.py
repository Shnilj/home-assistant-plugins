"""Stash entry point: read the add-on options, build the controller, serve the UI.

No MQTT yet — `controller.dirty` and `controller.summary()` are the hooks a
publisher will need when it arrives.
"""

from __future__ import annotations

import json
import logging
import os
import sys

from .controller import Controller
from .web import server

OPTIONS_PATH = "/data/options.json"
DEFAULTS = {"log_level": "info", "data_file": "/config/stash.json"}


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
    options = load_options(os.environ.get("OPTIONS_PATH", OPTIONS_PATH))
    setup_logging(os.environ.get("LOG_LEVEL") or options["log_level"])
    log = logging.getLogger("stash")

    data_file = os.environ.get("DATA_FILE") or options["data_file"]
    controller = Controller(path=data_file)
    summary = controller.summary()
    log.info(
        "Stash ready: %d items in %d spots across %d places, data in %s",
        summary["items"], summary["locations"], summary["places"], data_file,
    )
    server.serve(controller, port=int(os.environ.get("PORT", "8096")))


if __name__ == "__main__":
    main()
