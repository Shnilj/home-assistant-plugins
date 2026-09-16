# Changelog

## 0.1.0 — 2026-09-16

First version.

- Item catalogue with tags, "goes with" links and an always-pack flag.
- Trips with a day-by-day itinerary; day tags pull matching items onto the list.
- Suggestion cascade: adding an item offers what travels with it, one level at
  a time, so accepting a lens offers the cloth and the filter.
- Every item keeps a trail of why it is on the list.
- Dismissals are remembered per trip: "not this trip" stays not-suggested.
- Phone-first web UI behind ingress. No MQTT yet.
- Seeded with the Toscane 2026 itinerary and a starter catalogue of 83 items.
