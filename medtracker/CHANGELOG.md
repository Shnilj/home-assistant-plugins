# Changelog

## 0.1.0

Initial release.

- Track medications per subject (person / animal / other), each with its own
  schedule.
- Two schedule types: **fixed times** (e.g. half a pill at 08:00 and 20:00) and
  **every N hours** within an active window (e.g. one pill every 4 hours,
  08:00–22:00).
- Fractional doses (½, ⅓, ¼, ⅛, …) with a per-medication unit (pill, ml, drop,
  application, …).
- Home Assistant entities via retained MQTT device discovery: one device per
  subject plus a MedTracker hub device.
  - Per medication: state (upcoming / due / overdue / done), next due time,
    last taken, taken today, scheduled today, remaining today, dose summary, and
    **Take / Skip / Undo buttons**.
  - Per subject: due now, remaining today, taken today, next due, next
    medication, overdue, next summary, plus a **Take all due** button.
  - Hub: total due now, anyone overdue, next due, next summary (+ a due list as
    attributes for notification templates).
- Optional per-medication inventory: remaining count, estimated days left, and a
  low-stock sensor.
- Phone-friendly ingress web UI: a **Today** tap list to take/skip/undo doses,
  and a **Manage** view to add subjects, medications and schedules.
