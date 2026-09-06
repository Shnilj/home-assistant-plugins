# Changelog

## 0.2.0

- Multiple typed zones instead of one region. Draw as many **food** and **water**
  zones as you like (e.g. 2 bowls + 1 fountain) in the web UI; each is coloured
  and named, and you can add/remove them any time. Existing single-ROI setups are
  migrated automatically to one food zone.
- Smarter eating/drinking. A cat now has to actually cover a zone and lean into
  it (a posture gate) to count, so a cat sitting *beside* the bowl no longer
  registers. Food zones produce eating, water zones produce drinking.
- Tolerant of bowls moving a little (after cleaning, etc.) — the gate is measured
  relative to each zone, so a bowl nudged within its zone still works.
- New Home Assistant entities per cat: **drinking**, **last drank**, **drinks
  today**, plus global **current zone** and **current action** sensors.
- New options: `zone_coverage`, `require_lean_in`, `drink_dwell_seconds`,
  `drink_cooldown_minutes`.

## 0.1.3

- Fix wildly inflated meal counts. A cat holding still at the bowl was absorbed
  into the background, flickering motion off and splitting one meal into many.
  Presences are now debounced (`presence_grace_seconds`) and a meal is only
  counted once per `meal_cooldown_minutes` per cat, so one feeding window = one
  meal.
- Web UI: label training captures by multi-select — click images to select,
  then assign the whole batch to a cat (or delete) in one click.

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
