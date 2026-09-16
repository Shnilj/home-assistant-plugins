# Changelog

## 0.2.0 — 2026-09-16

The panel now looks like part of Home Assistant instead of a website inside it.

- **It follows your Home Assistant theme.** The ingress frame is served from
  Home Assistant's own origin, so the page reads the resolved theme variables
  off the parent document — custom themes included — and falls back to Home
  Assistant's defaults if that is ever not possible.
- **No more TripPack header.** Home Assistant already draws one above the
  frame; the old title bar was a second header stacked on it. The trip name,
  progress and count now live in one 44px strip.
- **Tabs moved to the bottom**, where a thumb reaches them, with icons.
- **Suggestions arrive in a sheet over the list**, one at a time, instead of a
  block that pushed the list off the screen — with *Add all* for when you do
  not want to answer sixty questions.
- **Denser rows.** The reason a thing is on the list is a few words on the
  right ("Camera", "Always", "19 Sep +1") rather than a truncated sentence
  under every row; the full trail is still behind the ⋯.

## 0.1.2 — 2026-09-16

- **Fix: the UI was unusable.** Nothing on the page could be clicked, because
  `.sheet` sets `display: flex` and an author rule beats the browser's own
  `[hidden] { display: none }` — so the modal overlay sat invisibly over the
  whole page from the moment it loaded. For the same reason all four tabs
  rendered stacked on top of each other and the tab bar did nothing. One
  `[hidden] { display: none !important; }` fixes all of it.
- Added an inline favicon, so the log stops reporting a 404 for `/favicon.ico`.

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
