# Home Assistant Add-on Authoring Guide (for AI agents)

You are building a **Home Assistant add-on** (what users loosely call a "hassio
plugin"). This document is your prompt and playbook. Follow it. It was distilled
from building the `catwatch/` add-on in this repository — treat that folder as
the **reference implementation** and copy its patterns.

An add-on is a Docker container the Home Assistant **Supervisor** builds and
runs. It only exists on **HA OS / Supervised** installs. It is NOT a Python
custom component (`custom_component`), and it is NOT a plain Docker container —
the Supervisor manages its lifecycle, config, ingress, and permissions.

---

## 0. Golden rules (read these first — each cost real debugging time)

1. **If you ship an `apparmor.txt`, it is ENFORCED automatically** just by
   existing. A too-strict profile makes the container die at boot with
   `/bin/sh: 0: cannot open /init: Permission denied`. The profile MUST allow
   `/init` and the s6-overlay paths. When in doubt, **do not ship one** — the
   Supervisor applies a correct default. See the working profile in §7.
2. **Pick the base image deliberately.** The default HA base is **Alpine (musl)**,
   where `numpy`/`opencv`/most scientific wheels won't install (no musl wheels →
   source builds that fail). If you need those, use a **Debian** base. See §5.
3. **Do NOT use `build.yaml`** — it is deprecated (Supervisor 2026.04+) and
   triggers a warning. Select the base image and set labels **in the Dockerfile**
   using the `BUILD_ARCH` build-arg. `BUILD_FROM` is no longer auto-injected. §5.
4. **Pin dependencies for old CPUs.** `numpy` 2.x manylinux wheels require an
   `x86-64-v2` CPU; many HA hosts (old Celeron/Atom/NUC, some VMs) don't have it
   and crash with `NumPy was built with baseline optimizations (X86_V2)`. Pin
   `numpy==1.26.4` (SSE2 baseline) and a compatible OpenCV (`opencv-python-headless==4.10.0.84`).
5. **On a Debian base, `pip install` needs `--break-system-packages`** (PEP 668).
6. **Use device-based MQTT discovery** to expose entities (§8), and get broker
   credentials from the Supervisor via `bashio::services` in `run.sh` (§6). Never
   hardcode broker settings.
7. **Ingress web UIs must use RELATIVE URLs** (`api/foo`, not `/api/foo`) — HA
   prepends the ingress base path. Bind the server to `0.0.0.0`.
8. **A local venv test harness catches logic bugs but NOT container issues.**
   AppArmor, base-image, architecture, and s6 problems only appear when the
   Supervisor builds and runs the container. Test both ways (§9).

---

## 1. Required file structure

```
<repo root>/
  repository.yaml            # marks this repo as an add-on repository
  README.md
  <addon-slug>/              # one folder per add-on
    config.yaml              # add-on manifest (REQUIRED)
    Dockerfile               # REQUIRED
    run.sh                   # entrypoint (bashio)
    requirements.txt         # if Python
    apparmor.txt             # OPTIONAL — omit unless you write it correctly (§7)
    icon.png                 # 256x256
    logo.png
    README.md
    DOCS.md                  # shown in the add-on's Documentation tab
    CHANGELOG.md             # bump on every change so the Supervisor offers Update
    translations/en.yaml     # labels/descriptions for config options
    <app code>/
```

`repository.yaml`:

```yaml
name: My Add-ons
url: https://github.com/<user>/<repo>
maintainer: Name <email>
```

---

## 2. config.yaml — the manifest

Key fields (see HA "Add-on configuration" docs for the full list):

```yaml
name: My Addon
version: "0.1.0"                 # bump every release; Supervisor keys "Update" off this
slug: myaddon
description: One-line description.
arch: [aarch64, amd64]           # list what you support
init: false                      # REQUIRED for modern s6-overlay base images
startup: application
boot: manual
ingress: true                    # sidebar web UI without exposing a port
ingress_port: 8099
panel_icon: mdi:some-icon
services:
  - mqtt:need                    # get MQTT broker creds from the Supervisor
map:
  - addon_config:rw              # mounts a persistent, user-visible dir at /config
options:                         # DEFAULT user config
  some_option: ""
schema:                          # VALIDATION for each option
  some_option: str
```

Option schema types: `str`, `int(min,max)`, `float(min,max)`, `bool`, `port`,
`email`, `url`, `password`, `list(a|b|c)`, `match(^regex$)`, a trailing `?`
makes it optional. Lists use `- str`.

**Storage model:**
- `/data` — private, persistent per-add-on. Put the model, internal state here.
  The Supervisor writes the user's options to `/data/options.json`.
- `/config` — mounted via `map: [addon_config:rw]`. Persistent and **user-visible**
  (browsable via the Samba / File editor add-ons). Put user-facing artifacts
  (snapshots, datasets, editable settings) here.

**Reading config at runtime:** read `/data/options.json` directly (JSON). Pass
only things that need Supervisor lookups (MQTT creds) via env from `run.sh`.

---

## 3. Dockerfile (Debian base, the correct 2026 pattern)

```dockerfile
# BUILD_ARCH is injected by the HA builder; the default keeps it buildable
# standalone. Debian base (not Alpine) so numpy/opencv install from wheels.
ARG BUILD_ARCH=amd64
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base-debian:bookworm

LABEL org.opencontainers.image.title="My Addon" \
      org.opencontainers.image.source="https://github.com/<user>/<repo>"

ENV LANG=C.UTF-8 PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

COPY app /app/app
COPY run.sh /run.sh
RUN chmod a+x /run.sh
WORKDIR /app
CMD [ "/run.sh" ]
```

If you don't need Debian-only wheels, the Alpine base
(`ghcr.io/home-assistant/${BUILD_ARCH}-base:latest`) is smaller. For OpenCV add
`libgl1 libglib2.0-0` to the apt install.

---

## 4. requirements.txt (pin for reproducibility and old CPUs)

```
numpy==1.26.4                     # <2 so it runs on CPUs without x86-64-v2
opencv-python-headless==4.10.0.84 # compatible with numpy 1.26; use -headless
paho-mqtt>=2.0,<3                 # 2.x API (CallbackAPIVersion.VERSION2)
Flask>=3.0,<4                     # if you serve an ingress UI
waitress>=3.0,<4                  # a real WSGI server (don't use Flask dev server)
```

---

## 5. Base-image selection notes

- Base images are multi-arch manifests now; `${BUILD_ARCH}-base-debian:bookworm`
  resolves to the right arch. `BUILD_ARCH` ∈ {`amd64`, `aarch64`, `armv7`, ...}.
- **No `build.yaml`** and **no reliance on `BUILD_FROM`** — both are gone/deprecated.
- Put image `LABEL`s in the Dockerfile, not in a separate file.

---

## 6. run.sh — entrypoint with bashio

```bash
#!/usr/bin/with-contenv bashio
set -e

if bashio::services.available "mqtt"; then
    export MQTT_HOST="$(bashio::services mqtt 'host')"
    export MQTT_PORT="$(bashio::services mqtt 'port')"
    export MQTT_USER="$(bashio::services mqtt 'username')"
    export MQTT_PASSWORD="$(bashio::services mqtt 'password')"
    bashio::log.info "MQTT at ${MQTT_HOST}:${MQTT_PORT}"
else
    bashio::log.warning "No MQTT service; install the Mosquitto broker add-on."
fi

export LOG_LEVEL="$(bashio::config 'log_level')"
cd /app
exec python3 -m app.main
```

With `init: false` and a modern s6 base, `CMD ["/run.sh"]` runs under s6.
`#!/usr/bin/with-contenv bashio` gives you env + the `bashio` helpers.

---

## 7. apparmor.txt — only if you ship one, and get it right

Shipping this file **enables enforcement**. If you don't need hardening, **omit
it** and the Supervisor uses a safe default. If you do ship one, it MUST allow
s6-overlay or the container won't boot:

```
#include <tunables/global>

profile <slug> flags=(attach_disconnected,mediate_deleted) {
  #include <abstractions/base>
  file,
  signal (send) set=(kill,term,int,hup,cont),

  # s6-overlay — REQUIRED, or you get "cannot open /init: Permission denied"
  /init ix,
  /bin/** ix,
  /usr/bin/** ix,
  /usr/local/bin/** ix,
  /run/{s6,s6-rc*,service}/** ix,
  /package/** ix,
  /command/** ix,
  /etc/s6-overlay/** ix,
  /etc/services.d/** rwix,
  /etc/cont-init.d/** rwix,
  /etc/cont-finish.d/** rwix,
  /run/{,**} rwk,
  /dev/tty rw,

  /usr/lib/bashio/** ix,
  /run.sh ix,
  /tmp/** rwk,

  /app/** r,
  /data/** rw,
  /config/** rw,
}
```

---

## 8. MQTT — device-based discovery

Expose entities to Home Assistant by publishing one **retained** discovery
message describing a device with all its components, then publish state to the
per-entity topics. Requires `services: [mqtt:need]` and the MQTT integration
enabled in HA.

- Discovery topic: `homeassistant/device/<device_id>/config`
- Payload shape (abbreviated keys): `dev` (device), `o` (origin), shared
  `availability_topic`, and `cmps` (components), each with a platform `p`,
  `unique_id`, `state_topic`, etc.

```json
{
  "dev": {"ids": "myaddon", "name": "My Addon", "sw": "0.1.0"},
  "o": {"name": "myaddon", "sw": "0.1.0"},
  "availability_topic": "myaddon/status",
  "payload_available": "online", "payload_not_available": "offline",
  "cmps": {
    "activity": {"p": "binary_sensor", "device_class": "motion",
                 "state_topic": "myaddon/activity", "unique_id": "myaddon_activity"},
    "count": {"p": "sensor", "state_class": "total",
              "state_topic": "myaddon/count", "unique_id": "myaddon_count"}
  }
}
```

Client tips (paho-mqtt 2.x):
- `mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=...)`.
- Set a **last-will** on `myaddon/status` → `offline` (retain), publish `online`
  on connect, and publish the discovery message on every `on_connect` (so it
  survives broker restarts).
- Publish discovery and states with `retain=True`.
- An `image` component (`"p": "image"`, `image_topic`, `content_type:"image/jpeg"`)
  lets you push a live JPEG (publish raw bytes to that topic).

---

## 9. Development & testing workflow

**Fast loop — local, no HA (catches logic bugs):** make the app runnable from a
plain venv by reading config from env/JSON and defaulting sane values. A
`test-local.sh` that creates a venv, installs `requirements.txt`, points
`DATA_DIR`/`CONFIG_DIR` at local folders, and runs `python3 -m app.main` lets you
iterate in seconds. See `catwatch/../test-local.sh`.

**What local testing CANNOT catch** (only a real Supervisor build/run will):
AppArmor denials, base-image/arch/wheel problems, s6/init issues, ingress
routing, and the MQTT-credentials handshake. Always do a real install too.

**Before every commit:**
- `python3 -m py_compile app/*.py ...` (syntax).
- Parse the YAML: `python3 -c "import yaml;yaml.safe_load(open('config.yaml'))"`.
- Unit-test pure logic (geometry, parsing, state machines) with a tiny script.

**Deploying a change to a running install:** bump `version` in `config.yaml`, add
a `CHANGELOG.md` entry, then in HA: Add-on Store → ⋮ → **Reload** → open the
add-on → **Update** (rebuilds the container). Uninstall + Install forces a clean
rebuild. **Read the add-on log after every start** — it's where these failures
surface.

---

## 10. Design principles (learned from CatWatch)

- **Local-first / privacy:** prefer on-device processing over cloud APIs; no data
  leaves the network unless the user opts in.
- **Assume a weak host:** low CPU, no GPU. Keep per-frame work cheap; make heavy
  models optional and pluggable behind one clear extension point.
- **Debounce real-world signals:** motion/sensors flicker. Use grace periods and
  cooldowns so one real-world event counts once (raw per-frame counting produced
  200 "meals" from ~12 in CatWatch — see its `presence_grace_seconds` /
  `*_cooldown_minutes`).
- **Make tuning user-facing:** expose thresholds as add-on options with
  translations, not hardcoded constants.
- **Give the add-on a small ingress UI** for setup/config that doesn't fit in
  the options schema (drawing regions, labelling data, previews).

---

## 11. Pre-ship checklist

- [ ] `config.yaml`: `version`, `slug`, `arch`, `init: false`, `schema` matches `options`.
- [ ] Dockerfile uses `BUILD_ARCH` + correct base; no `build.yaml`.
- [ ] Dependencies pinned; `--break-system-packages` on Debian.
- [ ] No `apparmor.txt`, OR one that allows `/init` and s6 paths.
- [ ] MQTT via `mqtt:need` + `bashio::services`; discovery is retained; LWT set.
- [ ] Ingress UI uses relative URLs; server binds `0.0.0.0`.
- [ ] Persistent user data under `/config`; private state under `/data`.
- [ ] `translations/en.yaml`, `DOCS.md`, `CHANGELOG.md`, `icon.png` present.
- [ ] Compiles, YAML parses, pure logic unit-tested.
- [ ] Verified by a REAL Supervisor build + start, log checked — not just locally.

---

## Reference implementation

`catwatch/` in this repository is a complete, working add-on that applies every
point above: RTSP capture, motion detection, a local pluggable classifier, an
ingress UI (Flask + waitress) with an interactive editor and data-labelling, and
MQTT device discovery. When unsure how to structure something, read the matching
file there and mirror it.
