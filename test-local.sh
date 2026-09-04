#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# CatWatch — Level 1 local test (no Home Assistant, no MQTT broker required).
#
# Sets up a Python virtualenv, installs the add-on's dependencies, and runs the
# app directly against your camera. The web UI comes up at http://localhost:8099
# where you can draw the bowl region, collect captures, label them, and train.
#
# Usage:
#   ./test-local.sh                         # uses/creates dev-data/options.json
#   ./test-local.sh rtsp://user:pass@ip/... # set (or update) the camera URL
#
# Environment overrides (all optional):
#   RTSP_URL=...        camera stream (same as the positional argument)
#   CATS="Ellie,Milo"   comma-separated cat names
#   MQTT_HOST=localhost also publish to a local broker (Level 2)
#   DETECTION_FPS=3     frames per second analysed
#   LOG_LEVEL=info      trace|debug|info|warning|error
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADDON_DIR="$SCRIPT_DIR/catwatch"
VENV_DIR="$ADDON_DIR/.venv"
DATA_DIR="$ADDON_DIR/dev-data"
CONFIG_DIR="$ADDON_DIR/dev-config"
OPTIONS_FILE="$DATA_DIR/options.json"
REQ_FILE="$ADDON_DIR/requirements.txt"
PORT=8099

blue()  { printf '\033[1;34m%s\033[0m\n' "$*"; }
green() { printf '\033[1;32m%s\033[0m\n' "$*"; }
yellow(){ printf '\033[1;33m%s\033[0m\n' "$*"; }

# --- 1. Python -------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install Python 3 first (e.g. 'brew install python')." >&2
  exit 1
fi

# --- 2. Virtualenv + dependencies -----------------------------------------
if [ ! -d "$VENV_DIR" ]; then
  blue "Creating virtualenv at catwatch/.venv ..."
  python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Only (re)install when requirements.txt changed since last run.
STAMP="$VENV_DIR/.requirements.sha"
NEW_SHA="$(shasum "$REQ_FILE" 2>/dev/null | awk '{print $1}' || true)"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP" 2>/dev/null)" != "$NEW_SHA" ]; then
  blue "Installing dependencies (first run may take a minute) ..."
  pip install --quiet --upgrade pip
  pip install --quiet -r "$REQ_FILE"
  echo "$NEW_SHA" > "$STAMP"
else
  green "Dependencies already up to date."
fi

# --- 3. Local data folders + options.json ---------------------------------
mkdir -p "$DATA_DIR" "$CONFIG_DIR"

RTSP_ARG="${1:-${RTSP_URL:-}}"

# Merge/create options.json without needing jq.
CATS_ENV="${CATS:-}" DETECTION_FPS_ENV="${DETECTION_FPS:-}" RTSP_ARG="$RTSP_ARG" \
OPTIONS_FILE="$OPTIONS_FILE" python3 - <<'PY'
import json, os

path = os.environ["OPTIONS_FILE"]
try:
    with open(path) as fh:
        opts = json.load(fh)
except (FileNotFoundError, ValueError):
    opts = {}

# Defaults on first creation.
opts.setdefault("rtsp_url", "")
opts.setdefault("cats", ["Ellie"])
opts.setdefault("detection_fps", 3)
opts.setdefault("motion_sensitivity", 25)
opts.setdefault("motion_min_area", 1500)
opts.setdefault("eating_dwell_seconds", 5)
opts.setdefault("classifier_confidence", 0.55)
opts.setdefault("save_captures", True)
opts.setdefault("jpeg_quality", 80)
opts.setdefault("log_level", os.environ.get("LOG_LEVEL", "info"))

if os.environ.get("RTSP_ARG"):
    opts["rtsp_url"] = os.environ["RTSP_ARG"]
if os.environ.get("CATS_ENV"):
    opts["cats"] = [c.strip() for c in os.environ["CATS_ENV"].split(",") if c.strip()]
if os.environ.get("DETECTION_FPS_ENV"):
    opts["detection_fps"] = int(os.environ["DETECTION_FPS_ENV"])

with open(path, "w") as fh:
    json.dump(opts, fh, indent=2)
print("rtsp_url =", opts["rtsp_url"] or "(not set)")
print("cats     =", ", ".join(opts["cats"]))
PY

if ! grep -q '"rtsp_url": ".\+"' "$OPTIONS_FILE"; then
  yellow ""
  yellow "No camera URL set yet. The UI will run but show 'No camera'."
  yellow "Re-run with your stream, e.g.:"
  yellow "  ./test-local.sh rtsp://user:pass@192.168.1.50:554/stream1"
  yellow "or edit catwatch/dev-data/options.json directly."
  yellow ""
fi

# --- 4. Run ----------------------------------------------------------------
green ""
green "Starting CatWatch — open the web UI at:  http://localhost:$PORT"
green "Press Ctrl+C to stop."
green ""

cd "$ADDON_DIR"
export DATA_DIR CONFIG_DIR
export LOG_LEVEL="${LOG_LEVEL:-info}"
[ -n "${MQTT_HOST:-}" ] && { export MQTT_HOST; export MQTT_PORT="${MQTT_PORT:-1883}"; blue "Publishing to MQTT at $MQTT_HOST:$MQTT_PORT"; }

exec python3 -m app.main
