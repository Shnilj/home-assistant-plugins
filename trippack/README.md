# TripPack

Packing lists that follow your itinerary. A Home Assistant add-on, sibling of
`catwatch/` and `medtracker/` in this repository.

- Items carry tags and "goes with" links, so adding the camera offers the
  batteries, the lens, the bag — one step at a time.
- Trips carry a day-by-day itinerary; day tags pull matching items onto the list.
- Every item keeps the trail of why it is on the list.

See `DOCS.md` for the full story. `tools/build_seed.py` regenerates
`app/seed/default.json`, which is what a fresh install writes to
`/config/trippack.json` inside the container.

## Layout

```
trippack/
├── config.yaml            add-on manifest (ingress on 8097)
├── Dockerfile             Debian base, pure-Python deps
├── run.sh                 bashio entry point
├── app/
│   ├── model.py           pure engine: suggestions, tag matching, reasons
│   ├── store.py           validation + atomic JSON persistence
│   ├── controller.py      locked state owner, hot reload, all mutations
│   ├── main.py            entry point
│   ├── seed/default.json  starter catalogue + Toscane 2026
│   └── web/               Flask API and the single-page UI
├── tests/                 pytest: the engine, the controller and the API
└── tools/build_seed.py    regenerate the seed
```

## Tests

```
cd trippack && python3 -m pytest -q
```

Needs `pytest` and `flask`. CI runs this on every push, alongside a manifest
check over every add-on in the repository.

## Status

v0.1.1, not yet built on the real Supervisor — that is the next step, and it
is the only thing a local test run cannot tell you (AppArmor, the base image,
s6, ingress). Web UI only, no MQTT entities yet; `controller.dirty` and
`controller.summary()` are the hooks for when they arrive.
