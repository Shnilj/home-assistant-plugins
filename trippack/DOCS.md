# TripPack

A packing list that knows what you are doing on which day.

Three things it does that a notes app does not:

1. **Items know what they travel with.** Add the camera and it offers spare
   batteries, a charger, SD cards, the wide lens, a cloth and the bag. Accept
   the lens and it offers the cloth and the polarising filter. One level at a
   time, so you never get a wall of forty things.
2. **The itinerary fills the list.** Tag day 5 as `hiking` and `swimming` and
   everything tagged the same way becomes a suggestion for that day.
3. **Every item remembers why it is there.** Tap an item and it tells you:
   "Mon 21 Sep, Lago dell'Accesa needs hiking", or "Goes with Camera".

## Install

The add-on lives in this repository, so it appears under **Settings →
Add-ons → Add-on store** once the repository is added. Install, start, and
open the sidebar panel.

## Options

| Option | Default | What it does |
| --- | --- | --- |
| `log_level` | `info` | `debug` if something misbehaves. |
| `data_file` | `/config/trippack.json` | Where everything is stored. |

Everything is in that one file: catalogue, trips, itineraries, packing state.
It is plain JSON, it is in your backups, and you can edit it by hand — the
add-on notices the change and reloads without a restart.

## How the pieces fit

**Items** have a name, a category, tags, a "goes with" list, and an optional
*always* flag.

- **Tags** describe the situation an item is for: `hiking`, `swimming`,
  `night_train`, `driving`, `photography`. They are how the itinerary finds it.
- **Goes with** is the suggestion link. It is one-directional and one step at a
  time: camera → batteries → charger.
- **Always** means it is offered for every trip regardless of tags: passport,
  toothbrush, chargers.

**Days** have a date, a title, tags and notes. The tags do the work.

**The list** holds an item once, with every reason it earned its place, and one
of three states: still to pack, packed, or leaving it behind.

**"Not this trip"** removes an item and stops it being suggested again for that
trip. Adding it manually later undoes that.

## Using it

- **Pack** — search and add, tick things off, or hit *Review* to see what the
  itinerary suggests. Tap the ⋯ on any row for the why-trail, "what goes with
  this?", and the leave-behind option.
- **Days** — your itinerary. Each day shows how many suggested items are not on
  the list yet and how many are still unpacked. *Add suggested* reviews just
  that day.
- **Items** — the catalogue. This is where you set tags and wire up what goes
  with what. Time spent here pays off on the next trip.
- **Trips** — switch trips, create a new one, or unpack everything to reuse a
  trip as a template.

## Next trip

Trips are independent, but the catalogue is shared. After Toscane, create a new
trip, add its days, tag them, and the same items come back with no re-typing.
*Unpack everything* on an old trip turns it into a template.

## Editing by hand

```json
{
  "active_trip": "toscane_2026",
  "items": [
    {
      "id": "camera",
      "name": "Camera",
      "category": "photo",
      "tags": ["photography"],
      "suggests": ["camera_batteries", "lens_wide"],
      "always": false,
      "notes": ""
    }
  ],
  "trips": [
    {
      "id": "toscane_2026",
      "name": "Toscane 2026",
      "days": [
        {"date": "2026-09-21", "title": "Lago dell'Accesa",
         "tags": ["swimming", "hiking"], "notes": ""}
      ],
      "packing": [
        {"item_id": "camera", "state": "packed",
         "reasons": [{"kind": "manual"}]}
      ],
      "dismissed": []
    }
  ]
}
```

A bad file is never silently overwritten: TripPack copies it aside as
`trippack.json.broken-<timestamp>` and refuses to start rather than losing your
list.

## MQTT and notifications

Not yet. The hooks are in place: `controller.dirty` fires on every change and
`controller.summary()` returns the numbers a sensor would want (packed, todo,
percentage, suggestions waiting). When it lands, the obvious entities are a
`trippack_<trip>` device with *items left to pack*, *percentage packed* and
*next day*, plus a notification the evening before departure listing what is
still outstanding.
