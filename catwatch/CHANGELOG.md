# Changelog

## 0.11.0

- **Teach CatWatch "not a cat".** The recogniser can now learn a background class
  from frames that have motion but no cat — empty night views, IR auto-gain
  flicker, reflections, a light switching. Previously it had no choice but to name
  its nearest cat, which is how a phantom "Ellie eating" appeared on a cat-less
  frame. Label such frames **🚫 Not a cat** (a new button in *Captures to label*,
  and a **🚫 not a cat** option in the history "correct…" menu), click **Train**,
  and CatWatch rejects those frames outright instead of inventing a meal. Marking
  a history event "not a cat" also removes it and undoes its count. Examples are
  stored in the dataset's `__none__` folder.

- **Stop phantom events from whole-scene motion.** Frames where the changed area
  fills most of the view (a running water fountain, lights switching, a camera
  glitch) are now ignored instead of being treated as a giant "cat" — new
  `max_motion_fraction` option (default 0.6).
- **Better snapshot frame in the dark.** The event snapshot is now chosen by how
  much the cat covers the bowl zone (a geometric measure) rather than recognition
  confidence, which at night could rate an empty frame higher than the real cat.

## 0.10.2

- **Correct local time.** The add-on now uses Home Assistant's configured
  timezone, so "today", the daily reset and the stats line up with local time
  instead of UTC.
- **Camera URL is masked** in the configuration screen (it contains your camera
  password). Clear and retype it to change it.

## 0.10.1

- **Better history thumbnails.** The event snapshot (and its training crop) is now
  taken from the clearest frame of the whole visit — the one with the highest
  recognition confidence — and finalised when the visit ends, instead of a single
  frame from the moment the meal was first logged. A grey/glitchy camera frame or
  an unlucky split-second no longer becomes the saved image.

## 0.10.0

- **Dutch translation** of the configuration options (`nl.yaml`).
- **Test suite + CI.** A pytest suite covers the pure logic (zones, history,
  stats, config, classifier), run automatically by GitHub Actions on every push
  alongside byte-compile and YAML validation.

## 0.9.0

- **Auto-recovery.** A `/health` endpoint reports the processing loop's liveness
  and a Supervisor `watchdog` restarts the add-on if it ever stops ticking.
- **Counters now survive restarts and reflect edits.** Daily meal/drink counts
  are derived from the durable stats store, so a mid-day restart no longer resets
  them — and correcting or deleting a history event now adjusts the counts (and
  weekly totals) accordingly.
- **Leaner backups.** Snapshots and event crops are excluded from Home Assistant
  backups; the trained dataset and settings are still included.

## 0.8.0

- **Health insight.** New per-cat Home Assistant sensors: **overdue** (a problem
  sensor that turns on when a cat hasn't eaten in `overdue_hours`, default 12; 0
  disables), **meals this week**, and **eating minutes this week**.
- **Last 7 days** summary chart on the Monitor tab — meals per day per cat, to
  spot trends (e.g. a cat gradually eating less).
- A small durable stats store (`/config/stats.json`) keeps daily totals beyond
  the snapshot window; the cat table shows an ⚠️ when a cat is overdue.

## 0.7.0

- **Unknown visits are now logged.** When a cat clearly visits a bowl but the
  recogniser can't confidently say which cat, that visit is recorded as an
  "❓ unknown" event in the History timeline (with a training crop). Use the
  "correct…" picker to label it — these are exactly the hard cases the model
  learns most from. Disable via the `log_unknown_visits` option.

## 0.6.0

- **Correct a wrong recognition, and teach the model.** Each event in the History
  timeline now has a "✎ correct…" picker. Choosing the right cat fixes the record
  **and** files that event's crop as a labelled training example for that cat, so
  correcting mistakes actively improves recognition. Click Train afterwards to
  apply. (Picking the same cat that's shown also works — it confirms a correct one
  into the training set.)
- Each event now stores a clean, unannotated crop for this purpose. Event crops
  are pruned with the event; crops filed into training by a correction are kept.

## 0.5.1

- New per-cat Home Assistant sensors: **last meal duration** and **last drink
  duration** (in seconds), set when each visit ends — so you can automate on
  unusually short/long visits. Also shown in the Monitor cat table.

## 0.5.0

- **Time spent at the bowl.** Each visit now records how long the cat stayed, so
  the History timeline reads e.g. "Ellie · 08:12 · 1m 35s". The Monitor "Now"
  line also shows a live "for m:ss" while a cat is currently eating/drinking.

## 0.4.3

- Add a live camera feed to the top of the Monitor tab (the interactive zone
  editor stays on the Zones tab). Click it to enlarge.

## 0.4.2

- Fix the "Evaluate accuracy" button doing nothing (its name collided with a
  built-in browser function).
- Organise the web UI into **Monitor / Zones / Training** tabs so it's not one
  long scroll.

## 0.4.1

- **Evaluate accuracy** button. Runs a leave-one-out test over your labelled
  crops (each crop classified using all the others) and reports per-recognizer
  accuracy, so you can see whether `embedding` really beats `signature` on your
  own cats. Includes a confusion matrix and thumbnails of the misclassified crops
  so you can spot and fix bad labels.

## 0.4.0

- **Much better cat recognition.** New neural **embedding** recognizer: a bundled
  MobileNetV2 (run locally through OpenCV's DNN — no new dependency, no cloud)
  turns each crop into a rich feature vector that's far more discriminative than
  colour alone and largely robust to lighting/IR. Default on; `recognizer:
  signature` keeps the old lightweight method.
- **Visit-level voting.** Recognition now votes across the whole visit instead of
  trusting a single frame, so an occasional misread no longer flips the result or
  restarts the visit. The winning cat is committed only if it clears
  `recognition_margin` (default 0.6), otherwise the visit is left unattributed —
  fewer wrong "who ate" calls.
- After updating, click **Train** once to rebuild the model with the new
  recognizer (your existing labelled crops are reused). More labelled examples,
  including night/IR shots, help the most.

## 0.3.2

- Click any history thumbnail (or the latest capture) to enlarge it full-screen;
  click anywhere or press Esc to close.
- Remove individual history events — hover a thumbnail and click ✕ to delete the
  event and its snapshot file.

## 0.3.1

- Add a per-cat "today" totals strip at the top of the History panel
  (e.g. "Ellie 3 🍽️ 5 💧"), so the day's counts sit alongside the timeline.

## 0.3.0

- **History timeline.** The web UI now shows a rolling archive of the last 24h of
  eating/drinking events — a thumbnail per event with the cat, action, zone and
  time, filterable per cat. So you can see at a glance when each cat ate and
  which one it was, not just the latest snapshot.
- Events and their snapshots older than the retention window are pruned
  automatically. New `history_hours` option (default 24, up to 168).

## 0.2.1

- Remove the deprecated `build.yaml` (Supervisor warned about it). Base-image
  selection now uses `BUILD_ARCH` in the Dockerfile and labels moved into it, so
  the Debian base is still chosen per architecture. No functional change.

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
