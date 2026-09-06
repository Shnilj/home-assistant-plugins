# Changelog

## 0.2.0

- **Multi-day courses / recurring schedules.** A medication can now recur across
  days, not just within a day: every N days or weeks, or on specific weekdays,
  with a start date and an end after N times or on a date. Examples: "a B12 shot
  every week, starting 1 Sep, for 6 weeks" or "an antibiotic twice a day for 5
  days". Plain medications (no recurrence) stay daily as before.
- Each medication now looks ahead: **next due** points to its next scheduled day
  when nothing is left today (e.g. next week for a weekly shot, tomorrow for a
  daily pill), and a subject's "next" summary shows the date when it isn't today.
- New per-course **Course** sensor (e.g. "3 of 6") and an `active_today` flag; the
  Today view shows non-today courses with their next date instead of buttons.
- Inventory **days-left** now accounts for the cadence (a weekly shot lasts ~7×
  longer per unit than a daily pill).

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
