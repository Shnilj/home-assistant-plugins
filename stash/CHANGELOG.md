# Changelog

## 0.2.0 — 2026-10-21

**Import.** Bring in a batch of things — say, a list made from a photo of a
compartment — without editing stash.json by hand.

- **Import** sits next to the count on Find, and under Places. Paste JSON or
  choose a .json file, optionally pick a spot for things that do not say where
  they are, then **Preview**.
- The preview is the real import run on a copy: new things, things that get
  added to ones you already have, new places, and anything left out with the
  reason. Nothing changes until you tap **Import**.
- Takes the stash.json shape (`places` + `items`), a `spot` with a list of
  `items`, a plain list, or a run of `{…},` objects copied out of a chat.
- Things you already have are matched by name, ignoring case and punctuation
  ("usb c cable" is "USB-C cable"): the new spot is added — or the count goes
  up if it is the same spot — and tags are merged. Importing the same batch
  twice therefore shows up as "added to things you have", never as duplicates.
- Places are reused by id, or by name in the same spot, and never
  overwritten; new places may refer to each other in any order.
- A spot pointing at an unknown place or outside a wall is left out and
  reported. A thing whose every spot was bad is skipped rather than imported
  as "not put anywhere".
- New `POST api/import` with `text` (or `data`), optional `spot`, and
  `dry_run` (default true).


## 0.1.0 — 2026-10-18

First version.

- **Places** nest as deep as needed: rooms, shelf walls, areas and boxes.
  A shelf wall is a grid of compartments (columns × rows) that counts from the
  left or the right and from the top or the bottom, so "14th from the right,
  2nd from the top" is how Stash says it back to you.
- **Things** can be in several places at once, each spot with its own count
  (or "not counted") and a note. Adding a thing where it already is adds to
  the count instead of making a second line.
- **Find** searches names, categories, tags and notes, ignoring case, accents
  and punctuation, and also finds places ("black box").
- **Places** tab: walk from the room to the wall to a compartment; the wall is
  drawn as a tappable grid with how much is in each compartment and the names
  of the boxes in it. "Add thing here" and "Save & add another" make filling a
  box one name at a time quick.
- The place picker remembers the last five spots you used, and can make a new
  box on the spot without leaving it.
- Resizing a wall refuses to strand anything outside it; flipping its
  counting direction renumbers what is on it so nothing physically moves.
  Deleting a box moves its contents to where the box stood.
- All data in `/config/stash.json`, hand edits picked up without a restart.
- No MQTT entities yet.
