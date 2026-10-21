"""HTTP layer. Flask for routing, waitress for serving, no templating.

Every URL the page asks for is relative, because Home Assistant serves this
behind /api/hassio_ingress/<token>/ and absolute paths would escape it.
"""

from __future__ import annotations

import logging
import os

from flask import Flask, jsonify, request, send_from_directory

from ..controller import ItemNotFound, LocationNotFound, PlaceNotFound
from ..store import ValidationError

LOG = logging.getLogger("stash.web")

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def _key(err):
    return err.args[0] if err.args else "?"


def _body():
    return request.get_json(silent=True) or {}


def create_app(controller):
    app = Flask(__name__, static_folder=None)

    # -- pages ------------------------------------------------------------

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/static/<path:filename>")
    def static_files(filename):
        return send_from_directory(STATIC, filename)

    @app.get("/health")
    def health():
        return jsonify({"ok": True})

    # -- reads ------------------------------------------------------------

    @app.get("/api/state")
    def api_state():
        return jsonify(controller.state())

    @app.get("/api/summary")
    def api_summary():
        return jsonify(controller.summary())

    @app.get("/api/search")
    def api_search():
        return jsonify(controller.search(request.args.get("q", "")))

    @app.get("/api/items/<item_id>")
    def api_item(item_id):
        return jsonify(controller.item(item_id))

    @app.get("/api/places/<place_id>")
    def api_place(place_id):
        cell = None
        if request.args.get("col") and request.args.get("row"):
            cell = {"col": request.args.get("col"), "row": request.args.get("row")}
        return jsonify(controller.place(place_id, cell))

    # -- places -----------------------------------------------------------

    @app.post("/api/places")
    def api_save_place():
        return jsonify(controller.save_place(_body()))

    @app.delete("/api/places/<place_id>")
    def api_delete_place(place_id):
        return jsonify(controller.delete_place(place_id))

    # -- items ------------------------------------------------------------

    @app.post("/api/items")
    def api_save_item():
        return jsonify(controller.save_item(_body()))

    @app.delete("/api/items/<item_id>")
    def api_delete_item(item_id):
        controller.delete_item(item_id)
        return jsonify({"ok": True})

    @app.post("/api/items/<item_id>/locations")
    def api_add_location(item_id):
        return jsonify(controller.add_location(item_id, _body()))

    @app.post("/api/items/<item_id>/locations/<location_id>")
    def api_update_location(item_id, location_id):
        return jsonify(controller.update_location(item_id, location_id, _body()))

    @app.post("/api/items/<item_id>/locations/<location_id>/step")
    def api_step(item_id, location_id):
        try:
            delta = int(_body().get("delta", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "delta must be a whole number"}), 400
        return jsonify(controller.step_qty(item_id, location_id, delta))

    @app.delete("/api/items/<item_id>/locations/<location_id>")
    def api_remove_location(item_id, location_id):
        return jsonify(controller.remove_location(item_id, location_id))

    # -- import -----------------------------------------------------------

    @app.post("/api/import")
    def api_import():
        body = _body()
        payload = body.get("text") if "text" in body else body.get("data")
        if payload is None:
            return jsonify({"error": "send the batch as \"text\" (JSON as a string) or \"data\""}), 400
        return jsonify(
            controller.import_batch(
                payload, body.get("spot"), dry_run=bool(body.get("dry_run", True))
            )
        )

    # -- errors -----------------------------------------------------------
    # Deliberately narrow: a stray KeyError from a bug should still be a 500
    # with a traceback in the log, not a quiet 404.

    @app.errorhandler(ValidationError)
    def _invalid(err):
        return jsonify({"error": str(err)}), 400

    @app.errorhandler(PlaceNotFound)
    def _no_place(err):
        return jsonify({"error": "No such place: %s" % _key(err)}), 404

    @app.errorhandler(ItemNotFound)
    def _no_item(err):
        return jsonify({"error": "No such item: %s" % _key(err)}), 404

    @app.errorhandler(LocationNotFound)
    def _no_location(err):
        return jsonify({"error": "That location is gone: %s" % _key(err)}), 404

    return app


def serve(controller, host="0.0.0.0", port=8096):
    from waitress import serve as waitress_serve

    app = create_app(controller)
    LOG.info("Stash web UI on %s:%s", host, port)
    waitress_serve(app, host=host, port=port, threads=8, clear_untrusted_proxy_headers=True)
