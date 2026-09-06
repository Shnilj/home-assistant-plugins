# CLAUDE.md

This repository is a **Home Assistant add-on repository** (add-ons are Docker
containers the HA Supervisor builds and runs on HA OS / Supervised installs).

## Before writing or changing an add-on here

**Read [`ADDON_AUTHORING_GUIDE.md`](./ADDON_AUTHORING_GUIDE.md) first.** It is the
authoritative playbook — file structure, templates, the gotchas that cost real
debugging time, and a pre-ship checklist. Mirror the `catwatch/` add-on, which is
the working reference implementation.

## Non-negotiables (full detail in the guide)

- A shipped `apparmor.txt` is **enforced**; it must allow `/init` and the
  s6-overlay paths, or omit it entirely.
- Use a **Debian** base (not the Alpine default) if you need numpy/opencv/wheels.
  Select it in the Dockerfile via `ARG BUILD_ARCH`; **no `build.yaml`**, and don't
  rely on `BUILD_FROM`.
- Pin `numpy==1.26.4` (older HA CPUs lack x86-64-v2). `pip` needs
  `--break-system-packages` on Debian.
- Expose entities via **retained MQTT device discovery**; get broker creds from
  `bashio::services` (`services: [mqtt:need]`). Ingress UIs use **relative URLs**.
- A local venv test does NOT catch container issues (AppArmor, base image, arch,
  s6, ingress). Always verify with a real Supervisor build and read the add-on log.

## Deploying a change to a running install

Bump `version` in the add-on's `config.yaml`, add a `CHANGELOG.md` entry, then in
HA: Add-on Store → ⋮ → Reload → open the add-on → Update (rebuilds).
