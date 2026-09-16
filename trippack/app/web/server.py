"""HTTP layer. Flask for routing, waitress for serving, no templating.

Every URL the page asks for is relative, because Home Assistant serves this
behind /api/hassio_ingress/<token>/ and absolute paths would escape it.
"""

from __future__ import annotations

import logging
import os

from flask import Flask, jsonify, request, send_from_directory

from .. import model, store
from ..controller import TripNotFound

LOG = logging.getLogger("trippack.web")
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


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
        return jsonify(controller.state(request.args.get("trip")))

    @app.get("/api/summary")
    def api_summary():
        return jsonify(controller.summary(request.args.get("trip")))

    @app.get("/api/candidates")
    def api_candidates():
        return jsonify(
            {
                "candidates": controller.candidates(
                    request.args.get("trip"), request.args.get("date")
                )
            }
        )

    @app.get("/api/chain/<item_id>")
    def api_chain(item_id):
        by_id = model.index_items(controller.catalog)
        chain = model.chain_from(controller.catalog, item_id)
        return jsonify(
            {
                "item_id": item_id,
                "chain": [
                    {"item_id": i, "name": by_id.get(i, {}).get("name", i)} for i in chain
                ],
            }
        )

    # -- packing list -----------------------------------------------------

    @app.post("/api/pack")
    def api_pack():
        body = request.get_json(silent=True) or {}
        item_id = body.get("item_id")
        if not item_id:
            return jsonify({"error": "item_id is required"}), 400
        return jsonify(
            controller.add(item_id, body.get("trip"), body.get("reason"))
        )

    @app.post("/api/pack/<item_id>/state")
    def api_pack_state(item_id):
        body = request.get_json(silent=True) or {}
        state = body.get("state")
        try:
            if state:
                entry = controller.set_state(item_id, state, body.get("trip"))
            else:
                entry = controller.toggle(item_id, body.get("trip"))
        except ValueError as err:
            return jsonify({"error": str(err)}), 400
        return jsonify(entry)

    @app.delete("/api/pack/<item_id>")
    def api_pack_remove(item_id):
        controller.remove(item_id, request.args.get("trip"))
        return jsonify({"ok": True})

    @app.post("/api/pack/<item_id>/dismiss")
    def api_dismiss(item_id):
        body = request.get_json(silent=True) or {}
        controller.dismiss(item_id, body.get("trip"))
        return jsonify({"ok": True})

    @app.post("/api/pack/<item_id>/undismiss")
    def api_undismiss(item_id):
        body = request.get_json(silent=True) or {}
        controller.undismiss(item_id, body.get("trip"))
        return jsonify({"ok": True})

    @app.post("/api/pull")
    def api_pull():
        body = request.get_json(silent=True) or {}
        return jsonify(
            controller.pull(
                body.get("trip"),
                body.get("date"),
                include_essentials=body.get("essentials", True),
            )
        )

    @app.post("/api/reset")
    def api_reset():
        body = request.get_json(silent=True) or {}
        controller.reset_trip(body.get("trip"))
        return jsonify({"ok": True})

    # -- catalog ----------------------------------------------------------

    @app.post("/api/items")
    def api_save_item():
        try:
            return jsonify(controller.save_item(request.get_json(silent=True) or {}))
        except store.ValidationError as err:
            return jsonify({"error": str(err)}), 400

    @app.delete("/api/items/<item_id>")
    def api_delete_item(item_id):
        controller.delete_item(item_id)
        return jsonify({"ok": True})

    # -- trips ------------------------------------------------------------

    @app.post("/api/trips")
    def api_save_trip():
        try:
            return jsonify(controller.save_trip(request.get_json(silent=True) or {}))
        except store.ValidationError as err:
            return jsonify({"error": str(err)}), 400

    @app.delete("/api/trips/<trip_id>")
    def api_delete_trip(trip_id):
        controller.delete_trip(trip_id)
        return jsonify({"ok": True})

    @app.post("/api/trips/<trip_id>/active")
    def api_set_active(trip_id):
        controller.set_active(trip_id)
        return jsonify({"ok": True})

    @app.post("/api/trips/<trip_id>/days")
    def api_save_day(trip_id):
        try:
            return jsonify(controller.save_day(trip_id, request.get_json(silent=True) or {}))
        except store.ValidationError as err:
            return jsonify({"error": str(err)}), 400

    @app.delete("/api/trips/<trip_id>/days/<date>")
    def api_delete_day(trip_id, date):
        controller.delete_day(trip_id, date)
        return jsonify({"ok": True})

    # -- errors -----------------------------------------------------------

    @app.errorhandler(TripNotFound)
    def _no_trip(err):
        return jsonify({"error": "No such trip: %s" % err}), 404

    @app.errorhandler(KeyError)
    def _no_key(err):
        return jsonify({"error": "Unknown id: %s" % err}), 404

    return app


def serve(controller, host="0.0.0.0", port=8097):
    from waitress import serve as waitress_serve

    app = create_app(controller)
    LOG.info("TripPack web UI on %s:%s", host, port)
    waitress_serve(app, host=host, port=port, threads=8, clear_untrusted_proxy_headers=True)
