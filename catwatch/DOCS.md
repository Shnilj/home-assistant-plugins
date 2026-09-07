# CatWatch

Local, motion-triggered cat recognition for Home Assistant. It watches your
food bowls through an RTSP camera, captures when something moves, works out
**which cat** it is with a model that runs entirely on your own hardware, and
publishes everything to Home Assistant over MQTT.

The first thing it's built for: knowing **when your cats eat and which one is
actually at the bowl** — for example so you can be alerted if a particular cat
hasn't eaten in a while.

---

## Requirements

- **Home Assistant OS or Supervised** (this is an add-on).
- An **MQTT broker** — the official **Mosquitto broker** add-on is the easiest.
  Install it first; CatWatch picks up the connection automatically.
- The **MQTT integration** enabled in Home Assistant (Settings → Devices &
  Services). This is what turns the discovery messages into entities.
- An **RTSP/ONVIF camera** pointed at the feeding station. A steady, well-lit,
  fairly close view of the bowls works best.

---

## Installation

1. Settings → Add-ons → Add-on Store → ⋮ → **Repositories** and add
   `https://github.com/jensdescamps/home-assistant-plugins`.
   (Or drop the repo into your `addons` share for a local install.)
2. Install **CatWatch** from the store.
3. Open the **Configuration** tab and set at least:
   - `rtsp_url` — your camera's stream, e.g.
     `rtsp://user:pass@192.168.1.50:554/stream1`
   - `cats` — your cats' names (one entity set is created per name).
4. Start the add-on, then open its **web UI** (sidebar → CatWatch, or the
   "Open Web UI" button).

---

## Configuration options

| Option | Default | What it does |
|---|---|---|
| `rtsp_url` | – | Camera stream URL. |
| `detection_fps` | `3` | Frames per second analysed. 2–4 is plenty. |
| `motion_sensitivity` | `25` | 1 = very sensitive, 100 = only big changes. |
| `motion_min_area` | `1500` | Smallest changed area (px) that counts as motion. |
| `eating_dwell_seconds` | `5` | How long a cat must stay before it counts as *eating* (filters cats passing by). |
| `meal_cooldown_minutes` | `15` | Minimum minutes between counted meals for one cat. Repeated visits within this window count as one meal. |
| `drink_dwell_seconds` | `3` | How long at a water zone before it counts as drinking (usually shorter than eating). |
| `drink_cooldown_minutes` | `10` | Minimum minutes between counted drinks for one cat. |
| `presence_grace_seconds` | `3` | Motion-free seconds tolerated before a visit is considered over (bridges a still cat blending into the background). |
| `zone_coverage` | `0.3` | Fraction of a bowl zone the cat must cover (0–1) to count as using it. |
| `require_lean_in` | `true` | Only count when the cat is bent over the bowl, not just sitting in the zone. Turn off for a top-down camera. |
| `history_hours` | `24` | How long the History timeline keeps event snapshots; older ones are deleted. |
| `cats` | `[Ellie]` | Your cats' names. |
| `classifier_confidence` | `0.55` | Below this, a cat is reported as `unknown`. |
| `save_captures` | `true` | Save crops so you can label them and improve recognition. |
| `jpeg_quality` | `80` | Quality of saved snapshots and the MQTT image. |
| `log_level` | `info` | Add-on log verbosity. |

The **zones** (food and water bowls) are drawn in the web UI, not here.

---

## First-run workflow

1. **Draw the zones.** In the web UI, pick **Food** or **Water**, then drag a box
   around each bowl or fountain (draw it a little larger than the bowl so a
   nudged bowl after cleaning still fits). Add as many as are out — e.g. two food
   bowls and one fountain. Zones save as you draw; remove any from the list.
2. **Let it collect examples.** Over the next day or two, each time a cat visits
   the bowls CatWatch saves a cropped photo under *Captures to label*.
3. **Label them.** Click the captures that show the same cat to select them
   (a green tick appears), then click that cat's button in the toolbar to file
   the whole batch at once — or **Delete** to bin the bad ones (blurry, empty,
   two cats at once). Aim for **20–40 good crops per cat**, in varied poses and
   lighting.
4. **Train.** Click **Train now**. Recognition switches on immediately; the
   *Model ready* pill turns green.
5. **Keep improving.** Whenever recognition is shaky, label a few more fresh
   captures and retrain. More varied examples = better accuracy.

### How eating and drinking are decided

A cat is recognised from the camera; whichever zone it covers decides the
action. To count, the cat must cover at least `zone_coverage` of the zone **and**
be leaning into it (`require_lean_in`) — its body rising above the bowl, head
down. That posture gate is what separates a cat actually eating from one sitting
*beside* the bowl. A **food** zone produces *eating*; a **water** zone produces
*drinking*.

Once a cat holds that over a zone for the dwell time (`eating_dwell_seconds` /
`drink_dwell_seconds`), the matching sensor turns on and the timestamp is
stamped. A new *meal* or *drink* is only counted if it's been at least the
cooldown (`meal_cooldown_minutes` / `drink_cooldown_minutes`) since that cat's
last one, so grazing counts once. Brief motion gaps (a still cat blends into the
background) are bridged by `presence_grace_seconds`.

Because the coverage is measured relative to each zone, a bowl that drifts a bit
inside its zone after cleaning still works — just keep the zone a touch larger
than the bowl. If a top-down camera makes the lean-in test fail, set
`require_lean_in: false`. If counts look high or low, tune the cooldowns.

---

## Entities created

CatWatch appears as a single **CatWatch** device with:

- **Activity** (`binary_sensor`, motion) — something is at the feeding area.
- **Current cat** (`sensor`) — who is there right now (`none` / `unknown` / a name).
- **Current zone** (`sensor`) — which bowl/fountain is in use.
- **Current action** (`sensor`) — `eating` / `drinking` / `none`.
- **Snapshot** (`image`) — the latest capture.

And, for each cat, e.g. *Ellie*:

- **Ellie eating** / **Ellie drinking** (`binary_sensor`) — on while she is.
- **Ellie last eaten** / **Ellie last drank** (`sensor`, timestamp).
- **Ellie meals today** / **Ellie drinks today** (`sensor`, reset at midnight).

---

## Example automations

**1 · Alert if a cat hasn't eaten in 12 hours.**
Handy for keeping an eye on a cat that needs to eat regularly (say, one on a
special diet).

```yaml
alias: Alert if Ellie hasn't eaten in 12h
trigger:
  - platform: state
    entity_id: sensor.catwatch_ellie_last_eaten
    for:
      hours: 12
condition:
  # Only during waking hours, and only if we actually have a reading.
  - condition: template
    value_template: "{{ states('sensor.catwatch_ellie_last_eaten') not in ['unknown','unavailable'] }}"
action:
  - service: notify.mobile_app_your_phone
    data:
      title: "Ellie hasn't eaten"
      message: >-
        No visit to the bowls since
        {{ as_timestamp(states('sensor.catwatch_ellie_last_eaten')) | timestamp_custom('%H:%M') }}.
```

**2 · Notify with a photo whenever a specific cat eats.**

```yaml
alias: Photo when Ellie eats
trigger:
  - platform: state
    entity_id: binary_sensor.catwatch_ellie_eating
    to: "on"
action:
  - service: notify.mobile_app_your_phone
    data:
      message: "Ellie is eating 🍽️"
      data:
        entity_id: image.catwatch_snapshot
```

**3 · Daily meal summary at 22:00.**

```yaml
alias: Daily cat meal summary
trigger:
  - platform: time
    at: "22:00:00"
action:
  - service: notify.mobile_app_your_phone
    data:
      title: "Cat meals today"
      message: >-
        Ellie: {{ states('sensor.catwatch_ellie_meals_today') }} ·
        (add your other cats here)
```

Replace `notify.mobile_app_your_phone` with your own notify service, and the
entity IDs with the slugs generated from your cat names.

---

## Tips for accuracy

- **Frame the bowls tightly** with the ROI so crops are mostly cat, not floor.
- **Consistent lighting** helps a lot; add a small always-on light if the area
  gets dark. Most cat visits happen at dawn/dusk.
- **Label mistakes matter** — a few wrong labels hurt more than a few missing
  ones. When in doubt, delete rather than mislabel.
- If two cats are at the bowls at once, the current model reports the dominant
  one. Delete those crops rather than labelling them.

### Recognising cats that look very similar

The default recogniser uses colour and coarse pattern, which is ideal for
visually distinct cats. If you ever need to separate look-alikes, the single
place to upgrade is `extract_feature()` in `app/classifier.py`: swap in a
neural embedding (e.g. a MobileNet feature extractor via `onnxruntime`) that
returns an L2-normalised vector. Training, storage, the web UI and MQTT all
keep working unchanged — only the feature vector gets smarter.

---

## Where data lives

- Event snapshots (the History timeline): `/addon_configs/<slug>_catwatch/snapshots/`
- Event log: `.../events.json` (cat, action, zone, time, snapshot per event)
- Training dataset (labelled crops): `.../dataset/<Cat name>/`
- Unlabelled captures: `.../dataset/_unlabeled/`
- Trained model: the add-on's private `/data/model.npz`

Browse these with the **Samba share** or **Studio Code Server** add-on. Nothing
is uploaded anywhere — capture, recognition and storage are all local.

---

## Troubleshooting

- **No camera / black frame** — check `rtsp_url` in a player like VLC first. Use
  the camera's *sub-stream* (lower resolution) for less CPU.
- **No entities in HA** — make sure the Mosquitto broker add-on is running and
  the MQTT integration is set up. The add-on log prints the broker it found.
- **Everything is `unknown`** — you haven't labelled and trained yet, or
  `classifier_confidence` is too high. Label ~20+ crops per cat and retrain.
- **Too many/few captures** — tune `motion_sensitivity` and `motion_min_area`,
  and tighten the ROI.
- **High CPU** — lower `detection_fps` and use the camera's sub-stream.
