# Stash

Stash answers one question: **where is it?** You tell it what you have and
where you put it; it tells you back in the words you would use standing in
front of the shelf.

## Getting started

1. Install the add-on and start it. **Stash** appears in the sidebar.
2. The first start creates `/config/stash.json` with an example: a *Man cave*
   with a *Left Kallax* and a *Right Kallax* (16 × 4 each), the space behind
   each, and one example USB-C cable in two places.
3. Open **Places → Man cave → Left Kallax → Edit** and set the real number of
   compartments across and high, and which side you count from. Do the same
   for the right one. Rename or delete whatever does not match your attic.
4. Delete the example cable once your own things are in.

## Places

| Kind        | Use it for                                                         |
|-------------|--------------------------------------------------------------------|
| Room        | The man cave, the garage, the shed.                                |
| Shelf wall  | A row of Kallax units. A grid of compartments: columns × rows.     |
| Area        | Somewhere without compartments: *behind the left Kallax*, a corner.|
| Box         | Anything you put things in: a box, a bin, a drawer, a bag.         |

Places nest freely: a box can sit in a compartment of a wall, another box can
sit in that box. A wall made of several Kallax units side by side is **one**
shelf wall — four 4×4 units next to each other is 16 across and 4 high — so
the numbering runs along the whole wall the way you count it in the attic.

**Counting.** Each wall counts its columns from the left or from the right,
and its rows from the top or the bottom. The grid in the app is always drawn
as the wall looks (left is left), with the numbers in your direction along the
edges. If you change the direction later, everything on the wall is
renumbered so nothing physically moves.

**Resizing** a wall keeps the corner you count from fixed: on a wall counted
from the right, adding columns adds them on the left end. Stash refuses a
resize that would leave something outside the wall and tells you what.

**Deleting** a place moves whatever was in it to where it stood: delete the
black box and its cables are now loose in that compartment.

## Things

A thing has a name, an optional category, tags and notes, and any number of
**spots**. Each spot has a count (leave it empty for "some, not counted") and
an optional note ("2 m, braided").

- **Find** lists everything by category, or searches as you type. `usbc`,
  `usb c` and `USB-C` all find *USB-C cable*; accents and case do not matter.
- Tap a thing to see every spot. Each part of the path is a link — tap
  *Left Kallax* or *14th from the right, 2nd from the top* to go there.
- **− / +** on a spot when you take one out or put one back.
- **⋯** on a spot to move it, set an exact count or a note, or remove it.
- **Also somewhere else** adds another spot.

### Filling a box quickly

Open the box under **Places**, tap **Add thing here**, type a name, then
**Save & add another**. The place and count stay; only the name clears.

The place picker also keeps your last five spots at the top, and can create a
new box right where you are browsing ("New box here…").

## The data file

Everything lives in one JSON file (option `data_file`, default
`/config/stash.json` — reachable over Samba / File editor under
`/addon_configs/<repository-id>_stash/`). It is safe to edit by hand; Stash picks up
the change on the next tap, no restart needed.

```json
{
  "version": 1,
  "places": [
    {"id": "man_cave", "name": "Man cave", "kind": "room", "parent": null},
    {"id": "left_kallax", "name": "Left Kallax", "kind": "grid",
     "parent": "man_cave", "cols": 16, "rows": 4,
     "count_cols_from": "right", "count_rows_from": "top"},
    {"id": "black_box_with_lid", "name": "Black box with lid",
     "kind": "container", "parent": "left_kallax",
     "cell": {"col": 14, "row": 2}}
  ],
  "items": [
    {"id": "usb_c_cable", "name": "USB-C cable", "category": "Cables",
     "tags": ["usb"], "notes": "",
     "locations": [
       {"id": "loc_1", "place": "black_box_with_lid", "qty": 3, "note": ""},
       {"id": "loc_2", "place": "right_kallax", "cell": {"col": 3, "row": 1},
        "qty": 2, "note": ""}
     ]}
  ]
}
```

- `cell` uses the wall's **own** numbering: `{"col": 14, "row": 2}` on a wall
  counted from the right is the 14th from the right. `[14, 2]` and `"14,2"`
  are accepted too.
- `kind` is `room`, `grid` (shelf wall), `area` or `container` (box).
- `qty: null` means "not counted".
- A spot that points at a place id that does not exist is kept and shown in
  red, so a typo never loses data. Fix the id and it comes back.
- If the file cannot be parsed at start-up, a copy is kept next to it as
  `stash.json.broken-<timestamp>`.

## API

The panel talks to a small JSON API, handy for scripts (all under the ingress
path):

| Method | Path | |
|---|---|---|
| GET  | `api/search?q=usb` | things and places matching every word |
| GET  | `api/state` | everything |
| GET  | `api/items/<id>` · `api/places/<id>[?col=&row=]` | one thing / place / compartment |
| POST | `api/items` · `api/places` | create, or update when `id` is given |
| POST | `api/items/<id>/locations` | add a spot `{place, cell, qty, note}` |
| POST | `api/items/<id>/locations/<loc>` | move / recount / note |
| POST | `api/items/<id>/locations/<loc>/step` | `{delta: -1}` |
| DELETE | `api/items/<id>` · `api/places/<id>` · `api/items/<id>/locations/<loc>` | |

## Updating

The web UI is baked into the image. After an update: **Add-on Store → ⋮ →
Reload**, then **Update** on the add-on page. A restart alone keeps the old UI.
