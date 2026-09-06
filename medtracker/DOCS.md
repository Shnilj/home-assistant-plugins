# MedTracker

Track which medicines each person or animal needs to take per day, mark doses
taken from your phone or a notification, and drive Home Assistant automations
off the resulting entities.

## Requirements

- The **MQTT** integration + a broker (the **Mosquitto broker** add-on is the
  easy choice). MedTracker requests MQTT via the Supervisor, so no broker
  settings to fill in.

## Setup

1. Install and start MedTracker.
2. Open the **Web UI** (sidebar → MedTracker). Go to **Manage** and add:
   - a **subject** (a person, an animal, or "other"), then
   - one or more **medications**, each with a schedule.
3. Entities appear automatically in Home Assistant: a **device per subject**
   plus a **MedTracker** hub device.

Your schedule is stored in `/addon_configs/<slug>/medications.json` (browsable
via the Samba / File editor add-ons); dose history lives in the add-on's private
`/data`.

## Schedules

Each medication uses one of two schedule types:

- **Fixed times** — a list of clock times, each with its own dose. This covers
  "half a pill twice a day" (½ at 08:00, ½ at 20:00) or "an eighth of a pill
  twice a day" (⅛ at 08:00, ⅛ at 20:00).
- **Every N hours** — a dose every N hours between a start and end time, e.g.
  one pill every 4 hours from 08:00 to 22:00.

Doses are fractional: the web UI has quick-pick buttons for 1, ½, ⅓, ¼ and ⅛,
or type any number. The **unit** (pill, ml, drop, application, …) is per
medication.

### Dose states

For each dose, and for the medication overall, MedTracker computes a state:

- **upcoming** — not due yet.
- **due** — within the "due-soon lead time" before, up to the "overdue after"
  grace period after, its scheduled time.
- **overdue** — past its time and still not taken.
- **done** — every dose today has been taken or skipped.

Tune the lead and grace windows in the add-on **Configuration** tab.

## Entities

### Hub device — "MedTracker"

| Entity | Type | Notes |
| --- | --- | --- |
| Total due now | sensor | Count of doses due/overdue right now. Its `due` attribute is a list of `{subject, medication, dose, state, due_at}` — handy for notification templates. |
| Anyone overdue | binary_sensor (problem) | On if any subject has an overdue dose. |
| Next due | sensor (timestamp) | Soonest upcoming dose across everyone. |
| Next summary | sensor | Human-readable "what's next". |

### Per-subject device — "MedTracker: <name>"

Aggregates for that subject: **Due now**, **Remaining today**, **Taken today**,
**Overdue** (problem), **Next due** (timestamp), **Next medication**, **Next
summary**, and a **Take all due** button.

### Per medication

| Entity | Type | Notes |
| --- | --- | --- |
| `<med>` state | sensor (enum) | upcoming / due / overdue / done / none. |
| `<med>` next due | sensor (timestamp) | Next untaken dose. |
| `<med>` last taken | sensor (timestamp) | |
| `<med>` taken today | sensor | |
| `<med>` scheduled today | sensor | |
| `<med>` remaining today | sensor | |
| `<med>` doses | sensor | "taken/scheduled", e.g. `1/2`. |
| `<med>` take / skip / undo | button | Mark the current dose taken, skip it, or undo the last taken. |

If inventory tracking is on for a medication you also get **inventory**
(remaining count), **days left** (estimate from the daily dose), and **low
stock** (problem) — the low-stock threshold is the add-on's "Low-stock warning
(days)" option.

Entity IDs follow `domain.medtracker_<subject>_<medication>_<field>`, e.g.
`sensor.medtracker_ellie_prednisolone_state` and
`button.medtracker_ellie_prednisolone_take`.

## Example automations

**Actionable reminder when a dose is due** (with a "Taken" button that marks it):

```yaml
automation:
  - alias: "Med due — Ellie Prednisolone"
    trigger:
      - trigger: state
        entity_id: sensor.medtracker_ellie_prednisolone_state
        to: due
    action:
      - action: notify.mobile_app_your_phone
        data:
          title: "Ellie's medication"
          message: >-
            {{ state_attr('sensor.medtracker_ellie_prednisolone_next_due','') }}
            Prednisolone is due.
          data:
            actions:
              - action: "MED_TAKE_ELLIE_PRED"
                title: "Mark taken"
  - alias: "Med taken from notification"
    trigger:
      - trigger: event
        event_type: mobile_app_notification_action
        event_data:
          action: "MED_TAKE_ELLIE_PRED"
    action:
      - action: button.press
        target:
          entity_id: button.medtracker_ellie_prednisolone_take
```

**Alert if anything is overdue for more than a bit:**

```yaml
automation:
  - alias: "Medication overdue"
    trigger:
      - trigger: state
        entity_id: binary_sensor.medtracker_anyone_overdue
        to: "on"
        for: "00:05:00"
    action:
      - action: notify.family
        data:
          title: "Medication overdue"
          message: "{{ state_attr('sensor.medtracker_total_due_now','due') | map(attribute='subject') | unique | join(', ') }} still have doses to take."
```

**Daily low-stock check** (template over all `*_low_stock` problem sensors), or
simply trigger on a specific medication's **low stock** sensor turning on.

## Notes

- MedTracker uses the container's local time (Home Assistant sets the add-on's
  timezone from your HA settings). Counters reset at local midnight — the new
  day simply starts with no doses recorded.
- Editing `medications.json` by hand is fine; MedTracker reloads it when it
  changes and republishes discovery.
