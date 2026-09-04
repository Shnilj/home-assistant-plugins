# Changelog

## 0.1.2

- Fix crash on start (`NumPy was built with baseline optimizations (X86_V2)`) on
  older CPUs that lack x86-64-v2. Pin `numpy==1.26.4` (SSE2 baseline wheels) and
  `opencv-python-headless==4.10.0.84`.

## 0.1.1

- Fix add-on failing to start with `cannot open /init: Permission denied`. The
  bundled AppArmor profile was too strict and blocked the s6-overlay init used
  by the base image; it now permits `/init` and the s6 paths.

## 0.1.0

Initial release.

- RTSP camera capture with automatic reconnect.
- Motion / change detection restricted to a configurable food-bowl region (ROI).
- Local, on-device cat recognition (colour/pattern signature classifier) — no
  images leave your network, no cloud, no per-image cost.
- Ingress web UI: live frame, draw the ROI, review captures and label them per
  cat, one-click (re)train.
- MQTT device discovery: activity sensor, current-cat sensor, live snapshot
  image, and per-cat "eating now" + "last eaten" entities.
- Example Home Assistant automations in `DOCS.md`.
