# Changelog

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
