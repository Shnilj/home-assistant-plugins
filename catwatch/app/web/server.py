"""Flask ingress UI: live frame, ROI editor, capture labelling, training.

Served under Home Assistant ingress, so all links/fetches are RELATIVE — the
ingress base path is prepended by HA automatically.
"""
from __future__ import annotations

import glob
import logging
import os

from flask import Flask, Response, jsonify, request, send_from_directory
from waitress import serve as waitress_serve
from werkzeug.utils import secure_filename

from .. import classifier, config
from ..state import ModelHolder, SharedState

log = logging.getLogger("catwatch.web")

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CatWatch</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; margin: 0; background: #f5f5f7; color: #1a1a1a; }
  @media (prefers-color-scheme: dark) { body { background: #16171a; color: #e8e8ea; } .card{background:#212226 !important;} }
  header { padding: 14px 20px; background: #3f51b5; color: #fff; font-size: 20px; font-weight: 600; }
  header small { font-weight: 400; opacity: .8; font-size: 13px; }
  main { max-width: 1100px; margin: 0 auto; padding: 16px; display: grid; gap: 16px; grid-template-columns: 1fr 1fr; }
  .card { background: #fff; border-radius: 12px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
  .card h2 { margin: 0 0 12px; font-size: 15px; text-transform: uppercase; letter-spacing: .04em; opacity: .7; }
  .full { grid-column: 1 / -1; }
  .pill { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 13px; margin: 2px; }
  .ok { background: #d5f5e0; color: #0a6b33; } .bad { background: #ffdede; color: #a10000; }
  #frameWrap { position: relative; display: inline-block; max-width: 100%; }
  #frame { max-width: 100%; border-radius: 8px; display: block; }
  #roiCanvas { position: absolute; inset: 0; cursor: crosshair; width: 100%; height: 100%; }
  img.snap { max-width: 100%; border-radius: 8px; }
  button { background: #3f51b5; color: #fff; border: 0; padding: 8px 14px; border-radius: 8px; font-size: 14px; cursor: pointer; }
  button.ghost { background: transparent; color: inherit; border: 1px solid #8888; }
  .cap { display: inline-block; text-align: center; margin: 6px; }
  .cap img { width: 120px; height: 120px; object-fit: cover; border-radius: 8px; }
  .cap select { width: 120px; margin-top: 4px; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  td { padding: 6px 4px; border-bottom: 1px solid #8882; }
  .muted { opacity: .6; font-size: 13px; }
</style>
</head>
<body>
<header>🐱 CatWatch <small>local cat recognition</small></header>
<main>
  <div class="card">
    <h2>Status</h2>
    <div id="status"></div>
  </div>

  <div class="card">
    <h2>Cats</h2>
    <table id="catTable"></table>
  </div>

  <div class="card full">
    <h2>Bowl region (ROI)</h2>
    <p class="muted">Drag a rectangle over the food bowls, then Save. Only motion inside it triggers captures. Leave empty to watch the whole frame.</p>
    <div id="frameWrap">
      <img id="frame" alt="camera frame">
      <canvas id="roiCanvas"></canvas>
    </div>
    <div style="margin-top:10px">
      <button onclick="saveRoi()">Save ROI</button>
      <button class="ghost" onclick="clearRoi()">Clear ROI</button>
      <span id="roiMsg" class="muted"></span>
    </div>
  </div>

  <div class="card">
    <h2>Latest capture</h2>
    <img id="snap" class="snap" alt="latest snapshot">
  </div>

  <div class="card">
    <h2>Recognition model</h2>
    <p class="muted">Label captures below to teach CatWatch your cats, then retrain. More labelled examples per cat = better recognition.</p>
    <button onclick="train()">Train now</button>
    <span id="trainMsg" class="muted"></span>
  </div>

  <div class="card full">
    <h2>Captures to label</h2>
    <div id="captures"></div>
  </div>
</main>

<script>
let CATS = [];
let roi = null;         // [x,y,w,h] in natural image pixels
let drawing = false, startX = 0, startY = 0;
const frame = document.getElementById('frame');
const canvas = document.getElementById('roiCanvas');
const ctx = canvas.getContext('2d');

function fit() { canvas.width = frame.clientWidth; canvas.height = frame.clientHeight; drawRoi(); }
function scaleX() { return frame.naturalWidth ? frame.clientWidth / frame.naturalWidth : 1; }
function scaleY() { return frame.naturalHeight ? frame.clientHeight / frame.naturalHeight : 1; }

function drawRoi() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!roi) return;
  ctx.strokeStyle = '#00e676'; ctx.lineWidth = 2;
  ctx.strokeRect(roi[0]*scaleX(), roi[1]*scaleY(), roi[2]*scaleX(), roi[3]*scaleY());
}
canvas.addEventListener('mousedown', e => { drawing = true; startX = e.offsetX; startY = e.offsetY; });
canvas.addEventListener('mousemove', e => {
  if (!drawing) return;
  ctx.clearRect(0,0,canvas.width,canvas.height);
  ctx.strokeStyle = '#00e676'; ctx.lineWidth = 2;
  ctx.strokeRect(startX, startY, e.offsetX-startX, e.offsetY-startY);
});
canvas.addEventListener('mouseup', e => {
  drawing = false;
  const x = Math.min(startX, e.offsetX), y = Math.min(startY, e.offsetY);
  const w = Math.abs(e.offsetX-startX), h = Math.abs(e.offsetY-startY);
  if (w < 8 || h < 8) return;
  roi = [Math.round(x/scaleX()), Math.round(y/scaleY()), Math.round(w/scaleX()), Math.round(h/scaleY())];
  drawRoi();
});

async function saveRoi() {
  await fetch('api/roi', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({roi})});
  document.getElementById('roiMsg').textContent = 'Saved ✓';
  setTimeout(()=>document.getElementById('roiMsg').textContent='', 2000);
}
async function clearRoi() {
  roi = null; drawRoi();
  await fetch('api/roi', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({roi:null})});
}

async function train() {
  document.getElementById('trainMsg').textContent = 'Training…';
  const r = await fetch('api/train', {method:'POST'});
  const j = await r.json();
  document.getElementById('trainMsg').textContent = j.trained
    ? `Trained on ${j.samples} images ✓` : 'No labelled images yet.';
  loadCaptures();
}

async function loadStatus() {
  const r = await fetch('api/status'); const j = await r.json();
  const s = j.status;
  const pill = (ok, on, off) => `<span class="pill ${ok?'ok':'bad'}">${ok?on:off}</span>`;
  document.getElementById('status').innerHTML =
    pill(s.camera_connected,'Camera','No camera') +
    pill(s.mqtt_connected,'MQTT','No MQTT') +
    pill(s.model_ready,'Model ready','Model empty') +
    `<div style="margin-top:10px">Now at bowls: <b>${s.current_cat}</b>` +
    (s.current_cat!=='none' ? ` (${(s.current_confidence*100).toFixed(0)}%)` : '') + `</div>`;
  let rows = '';
  for (const [name, c] of Object.entries(j.cats)) {
    rows += `<tr><td><b>${name}</b></td><td>${c.eating?'🍽️ eating':'—'}</td>`
         + `<td>${c.meals_today} meals today</td>`
         + `<td class="muted">${c.last_eaten ? new Date(c.last_eaten).toLocaleString() : 'never'}</td></tr>`;
  }
  document.getElementById('catTable').innerHTML = rows;
  if (j.roi) { roi = j.roi; drawRoi(); }
}

async function loadCats() { CATS = await (await fetch('api/cats')).json(); }

async function loadCaptures() {
  const files = await (await fetch('api/captures')).json();
  const opts = ['<option value="">— pick cat —</option>']
    .concat(CATS.map(c=>`<option value="${c}">${c}</option>`))
    .concat('<option value="_delete">🗑 delete</option>').join('');
  document.getElementById('captures').innerHTML = files.length ? files.map(f =>
    `<div class="cap"><img src="api/captures/${f}"><br>
      <select onchange="label('${f}', this.value)">${opts}</select></div>`).join('')
    : '<span class="muted">No captures yet. They appear here when a cat visits the bowls.</span>';
}
async function label(file, cat) {
  if (!cat) return;
  await fetch('api/label', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({file, cat})});
  loadCaptures();
}

frame.addEventListener('load', fit);
window.addEventListener('resize', fit);
function refreshFrame() { frame.src = 'api/frame.jpg?t=' + Date.now(); }
function refreshSnap() { document.getElementById('snap').src = 'api/snapshot.jpg?t=' + Date.now(); }

loadCats().then(loadCaptures);
loadStatus(); refreshFrame(); refreshSnap();
setInterval(loadStatus, 2000);
setInterval(refreshFrame, 1500);
setInterval(refreshSnap, 3000);
setInterval(loadCaptures, 8000);
</script>
</body>
</html>
"""


def _list_captures(limit=60):
    files = glob.glob(os.path.join(config.UNLABELED_DIR, "*.jpg"))
    files.sort(key=os.path.getmtime, reverse=True)
    return [os.path.basename(f) for f in files[:limit]]


def create_app(state: SharedState, settings: config.Settings, model_holder: ModelHolder):
    app = Flask(__name__)

    @app.get("/")
    def index():
        return Response(INDEX_HTML, mimetype="text/html")

    @app.get("/api/cats")
    def api_cats():
        return jsonify(settings.cats)

    @app.get("/api/status")
    def api_status():
        data = state.snapshot_status()
        data["roi"] = config.load_roi()
        return jsonify(data)

    @app.get("/api/frame.jpg")
    def api_frame():
        jpg = state.get_frame()
        if not jpg:
            return ("", 204)
        return Response(jpg, mimetype="image/jpeg")

    @app.get("/api/snapshot.jpg")
    def api_snapshot():
        jpg = state.get_snapshot()
        if not jpg:
            return ("", 204)
        return Response(jpg, mimetype="image/jpeg")

    @app.post("/api/roi")
    def api_roi():
        roi = (request.get_json(silent=True) or {}).get("roi")
        config.save_roi(roi if roi else None)
        return jsonify({"ok": True})

    @app.get("/api/captures")
    def api_captures():
        return jsonify(_list_captures())

    @app.get("/api/captures/<path:name>")
    def api_capture_img(name):
        safe = secure_filename(name)
        return send_from_directory(config.UNLABELED_DIR, safe)

    @app.post("/api/label")
    def api_label():
        body = request.get_json(silent=True) or {}
        fname = secure_filename(body.get("file", ""))
        cat = body.get("cat", "")
        src = os.path.join(config.UNLABELED_DIR, fname)
        if not fname or not os.path.exists(src):
            return jsonify({"ok": False, "error": "not found"}), 404
        if cat == "_delete":
            os.remove(src)
            return jsonify({"ok": True})
        if cat not in settings.cats:
            return jsonify({"ok": False, "error": "unknown cat"}), 400
        dst_dir = settings.dataset_dir_for(cat)
        os.makedirs(dst_dir, exist_ok=True)
        os.replace(src, os.path.join(dst_dir, fname))
        return jsonify({"ok": True})

    @app.post("/api/train")
    def api_train():
        summary = classifier.train()
        if summary["trained"]:
            model_holder.set(classifier.SignatureModel.load())
        return jsonify(summary)

    return app


def serve(state, settings, model_holder, camera=None):
    app = create_app(state, settings, model_holder)
    log.info("Web UI listening on :8099 (ingress)")
    waitress_serve(app, host="0.0.0.0", port=8099, threads=6)
