# Changelog

## 0.1.1 — 2026-09-16

- **Fix: hand edits to `trippack.json` are no longer overwritten.** Only the
  read paths reloaded the file, so editing it while the page was open and then
  tapping anything wrote the stale in-memory copy back over the edit. Every
  public method now reloads first.
- Moved from `config:rw` to `addon_config:rw`. TripPack gets its own folder
  under `/addon_configs/` instead of write access to the whole Home Assistant
  configuration directory. **The data file moves** — copy your old
  `/config/trippack.json` across if you had already started a list.
- An unknown trip id is a 404 instead of a blank page, and only a genuinely
  unknown item id produces a 404 — other `KeyError`s are bugs and now say so.
- Dependencies live in `requirements.txt`; added `icon.png` and `logo.png`;
  removed two stale duplicate files from the add-on root.

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
