# 💊 MedTracker

Keep track of which medicines each **person or animal** needs to take, and when.

MedTracker turns a simple schedule into live Home Assistant entities you can
build reminders and notifications on — and gives you a phone-friendly page (in
the HA sidebar) to tap a dose as **taken**, **skipped**, or **undo** it.

## What it does

- One or more **subjects** (a person, a pet, anything), each with their own
  medications.
- Flexible schedules per medication:
  - **Fixed times** — e.g. *½ pill at 08:00 and ½ pill at 20:00*, or
    *⅛ pill twice a day*.
  - **Every N hours** — e.g. *1 pill every 4 hours between 08:00 and 22:00*.
- **Fractional doses** (½, ⅓, ¼, ⅛ …) with a unit you choose (pill, ml, drop, …).
- **Entities for automations**: per-medication state (upcoming / due / overdue /
  done), next-due timestamps, counts, and **Take / Skip / Undo buttons** so a
  notification action can mark a dose taken.
- Optional **inventory**: remaining count, estimated **days left**, and a
  low-stock warning.

Everything runs locally on your own hardware and talks to Home Assistant over
MQTT.

## Setup

1. Install the **Mosquitto broker** add-on and the **MQTT** integration if you
   haven't already.
2. Install MedTracker, start it, and open its **Web UI** from the sidebar.
3. Add your subjects and their medications on the **Manage** tab.
4. Your entities appear in Home Assistant under a device per subject (and a
   *MedTracker* hub device).

See [DOCS.md](./DOCS.md) for the full entity list and example automations.
