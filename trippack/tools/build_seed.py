#!/usr/bin/env python3
"""Regenerate app/seed/default.json.

The seed is what TripPack writes to /config/trippack.json on first run: a
starter catalog of items with their tags and suggestion links, plus the
Toscane 2026 itinerary. Edit here, run this, commit the JSON.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from app import store  # noqa: E402  (after sys.path fix)

# id, name, category, tags, suggests, always, notes
ITEMS = [
    # --- papers ---------------------------------------------------------
    ("passport", "Identity card / passport", "papers", [], [], True, ""),
    ("ehic", "European health insurance card", "papers", [], [], True, ""),
    ("travel_insurance", "Travel insurance details", "papers", [], [], True, ""),
    ("train_tickets", "European Sleeper tickets", "papers", ["night_train"], [], False,
     "Out 17/09 19.06 Brussel-Zuid, back 25/09 16.00 Milano Porta Garibaldi."),
    ("bookings", "Hotel and rental confirmations, offline", "papers",
     ["check_in", "travel_day"], [], True, ""),
    ("drivers_license", "Driving licence", "papers", ["car_rental", "driving"],
     ["credit_card", "car_voucher"], False, ""),
    ("credit_card", "Credit card for the car deposit", "papers", ["car_rental"], [], False,
     "Rental deposits usually need a credit card in the driver's name."),
    ("car_voucher", "Car rental voucher", "papers", ["car_rental"], [], False, ""),
    ("ztl_notes", "ZTL and parking notes, offline", "papers", ["driving", "city"], [], False,
     "Pisa, Lucca and Firenze centres are ZTL. Park outside and walk in."),
    ("cupola_tickets", "Timed tickets for the Cupola", "papers", ["booking"], [], False,
     "Brunelleschi's dome is timed entry — book before the day."),
    ("cash", "Cash in euros", "papers", [], [], True, ""),
    ("parking_coins", "Coins for parking machines", "papers", ["driving", "city"], [], False, ""),

    # --- tech -----------------------------------------------------------
    ("phone", "Phone", "tech", [], ["phone_charger", "powerbank", "usb_cables"], True, ""),
    ("phone_charger", "Phone charger", "tech", [], [], False, ""),
    ("powerbank", "Powerbank", "tech", ["travel_day", "hiking", "sightseeing"],
     ["usb_cables"], False, ""),
    ("usb_cables", "USB-C cables", "tech", [], [], False, ""),
    ("plug_adapter", "Italian plug adapter, type L", "tech", [], [], True,
     "Older Italian sockets are type L — a Belgian plug will not always fit."),
    ("headphones", "Headphones", "tech", ["night_train", "travel_day"],
     ["offline_media"], False, ""),
    ("offline_media", "Downloaded maps, series and podcasts", "tech",
     ["night_train", "travel_day", "driving"], [], False,
     "No signal in the Apennine tunnels and not much in the Maremma."),
    ("ereader", "E-reader", "tech", ["night_train", "beach"], ["ereader_charger"], False, ""),
    ("ereader_charger", "E-reader charger", "tech", [], [], False, ""),
    ("watch_charger", "Watch charger", "tech", [], [], False, ""),

    # --- photo ----------------------------------------------------------
    ("camera", "Camera", "photo", ["photography"],
     ["camera_batteries", "camera_charger", "sd_cards", "lens_wide", "lens_cloth",
      "camera_bag"], False, ""),
    ("camera_batteries", "Spare camera batteries", "photo", [], ["camera_charger"], False, ""),
    ("camera_charger", "Camera battery charger", "photo", [], [], False, ""),
    ("sd_cards", "Spare SD cards", "photo", [], [], False, ""),
    ("lens_wide", "Wide lens", "photo", [], ["lens_cloth", "lens_filter"], False, ""),
    ("lens_cloth", "Lens cloth", "photo", [], [], False, ""),
    ("lens_filter", "Polarising filter", "photo", [], [], False,
     "Cuts the haze over the Val d'Orcia."),
    ("camera_bag", "Camera bag", "photo", [], ["rain_cover"], False, ""),
    ("rain_cover", "Rain cover for the bag", "photo", [], [], False, ""),
    ("tripod", "Travel tripod", "photo", ["golden_hour"], ["camera_batteries"], False,
     "Montepulciano at golden hour, Vitaleta at dusk."),

    # --- the sleeper ----------------------------------------------------
    ("eye_mask", "Eye mask", "sleeper", ["night_train"], [], False, ""),
    ("earplugs", "Earplugs", "sleeper", ["night_train"], [], False, ""),
    ("travel_pillow", "Travel pillow", "sleeper", ["night_train"], [], False, ""),
    ("sleepwear", "Sleepwear", "sleeper", ["night_train"], [], False, ""),
    ("night_pouch", "Overnight pouch for the cabin", "sleeper", ["night_train"],
     ["wet_wipes", "toothbrush"], False,
     "Small enough to keep in the bunk instead of digging through the case."),
    ("wet_wipes", "Wet wipes", "sleeper", [], [], False, ""),
    ("slip_ons", "Slip-ons for the corridor", "sleeper", ["night_train"], [], False, ""),
    ("train_food", "Food and drink for the train", "sleeper",
     ["night_train", "travel_day"], ["water_bottle"], False,
     "Departure is 19.06 — dinner happens on board."),
    ("water_bottle", "Refillable water bottle", "sleeper",
     ["night_train", "hiking", "walking", "travel_day"], [], False, ""),

    # --- clothes --------------------------------------------------------
    ("tshirts", "T-shirts", "clothes", [], [], True, ""),
    ("underwear", "Underwear", "clothes", [], [], True, ""),
    ("socks", "Socks", "clothes", [], [], True, ""),
    ("trousers", "Trousers", "clothes", [], [], True, ""),
    ("shorts", "Shorts", "clothes", ["beach", "swimming", "walking"], [], False, ""),
    ("light_jumper", "Light jumper for the evenings", "clothes",
     ["golden_hour", "night_train"], [], False, ""),
    ("rain_jacket", "Rain jacket", "clothes", ["hiking", "nature", "walking"], [], False, ""),
    ("nice_outfit", "Something nicer for dinner", "clothes", ["city"], [], False, ""),
    ("walking_shoes", "Comfortable walking shoes", "clothes",
     ["walking", "city", "sightseeing", "climbing"], [], True, ""),
    ("laundry_bag", "Laundry bag", "clothes", [], [], True, ""),

    # --- wash -----------------------------------------------------------
    ("toiletry_bag", "Toiletry bag", "wash", [],
     ["toothbrush", "deodorant", "shower_stuff", "razor", "sunscreen"], True, ""),
    ("toothbrush", "Toothbrush and toothpaste", "wash", [], [], False, ""),
    ("deodorant", "Deodorant", "wash", [], [], False, ""),
    ("shower_stuff", "Shampoo and shower gel", "wash", [], [], False, ""),
    ("razor", "Razor", "wash", [], [], False, ""),
    ("quick_dry_towel", "Quick-dry towel", "wash",
     ["swimming", "beach", "hot_spring"], [], False, ""),

    # --- health ---------------------------------------------------------
    ("medication", "Medication", "health", [], ["first_aid"], True, ""),
    ("first_aid", "Small first-aid kit", "health", ["hiking", "driving"],
     ["blister_plasters", "painkillers"], False, ""),
    ("blister_plasters", "Blister plasters", "health", ["hiking", "walking"], [], False, ""),
    ("painkillers", "Painkillers", "health", [], [], False, ""),
    ("sunscreen", "Sunscreen", "health",
     ["beach", "swimming", "hiking", "walking", "sightseeing", "hot_spring"], [], False, ""),
    ("insect_repellent", "Insect repellent", "health", ["nature", "hiking", "swimming"],
     [], False, "Pine woods and a lake full of frogs."),
    ("motion_sickness", "Travel sickness tablets", "health", ["driving"], [], False, ""),
    ("hand_gel", "Hand gel", "health", ["travel_day"], [], False, ""),

    # --- outdoors -------------------------------------------------------
    ("hiking_shoes", "Hiking shoes", "outdoors", ["hiking"],
     ["hiking_socks", "blister_plasters", "daypack"], False, ""),
    ("hiking_socks", "Hiking socks", "outdoors", [], [], False, ""),
    ("daypack", "Daypack", "outdoors", ["hiking", "sightseeing", "walking", "climbing"],
     ["water_bottle", "sunscreen", "rain_cover"], False, ""),
    ("cap", "Cap or hat", "outdoors", ["hiking", "beach", "walking", "swimming"], [], False, ""),
    ("sunglasses", "Sunglasses", "outdoors",
     ["driving", "beach", "walking", "sightseeing"], [], False, ""),

    # --- water ----------------------------------------------------------
    ("swimwear", "Swimwear", "water", ["swimming", "beach", "hot_spring"],
     ["quick_dry_towel", "flipflops", "dry_bag", "sunscreen"], False,
     "Needed the same day the car is collected — keep it reachable, not buried."),
    ("flipflops", "Flip-flops", "water", ["beach", "swimming", "night_train"], [], False, ""),
    ("dry_bag", "Dry bag", "water", ["swimming", "beach"], [], False, ""),
    ("water_shoes", "Water shoes", "water", ["swimming"], [], False,
     "Lago dell'Accesa has a stony entry."),
    ("goggles", "Swimming goggles", "water", ["swimming"], [], False, ""),

    # --- car ------------------------------------------------------------
    ("phone_mount", "Phone mount for the car", "car", ["driving"], ["car_charger"], False, ""),
    ("car_charger", "Car USB charger", "car", ["driving"], [], False, ""),
    ("car_photos", "Photos of the car at pickup and drop-off", "car",
     ["car_rental", "car_return"], [], False,
     "Five minutes of photos settles every damage argument later."),

    # --- bags -----------------------------------------------------------
    ("suitcase", "Suitcase", "bags", [], [], True, ""),
    ("packing_cubes", "Packing cubes", "bags", [], [], False, ""),
    ("foldable_bag", "Foldable bag for the way back", "bags", ["groceries"], [], False,
     "Pecorino and wine need somewhere to live."),
    ("shopping_bag", "Reusable shopping bag", "bags", ["groceries"], [], False, ""),
    ("cool_bag", "Cool bag", "bags", ["groceries", "beach"], [], False, ""),
]

DAYS = [
    ("2026-09-17", "Vertrek European Sleeper",
     ["night_train", "travel_day", "departure"],
     "Rond 16u vertrek, Freddy voert ons. 19.06 uit Brussel-Zuid, rond 18.30 aan het perron."),
    ("2026-09-18", "Milaan",
     ["city", "walking", "travel_day", "check_in"],
     "11.40 aankomst Milano Porta Garibaldi, S5 naar Milano Certosa, 2 min naar het hotel. "
     "Daarna Milaan op ons gemak."),
    ("2026-09-19", "Auto ophalen en Tomboli di Cecina",
     ["car_rental", "driving", "check_in", "nature", "walking", "swimming", "beach",
      "groceries"],
     "3,5 a 4 uur rijden naar Toscane, Cinque Terre optioneel onderweg. Inchecken, zwemkleding "
     "uit de bagage, dan het kustbos en de vrije stranden. Supermarkt op de terugweg."),
    ("2026-09-20", "Pisa en Lucca",
     ["city", "walking", "sightseeing", "photography", "driving"],
     "Highlights van Pisa, daarna een half uur naar Lucca voor de avondzon."),
    ("2026-09-21", "Lago dell'Accesa en het Etruskische pad",
     ["swimming", "hiking", "nature", "photography", "driving"],
     "Kristalhelder meer bij Massa Marittima. Archeologisch pad van zo'n 75 minuten, "
     "soms oneffen en steil. 's Avonds terug naar het verblijf."),
    ("2026-09-22", "Firenze",
     ["city", "walking", "sightseeing", "photography", "climbing", "booking"],
     "Stadsdag in Florence. Cupola del Brunelleschi vooraf boeken."),
    ("2026-09-23", "Pienza, Val d'Orcia en Montepulciano",
     ["driving", "walking", "sightseeing", "photography", "golden_hour", "hot_spring",
      "swimming"],
     "Ontbijt onderweg. Stadsmuur van Pienza, lunch met pecorino, Cappella della Madonna di "
     "Vitaleta na 10 a 15 min wandelen. Eventueel een warmwaterbron. Afsluiten in "
     "Montepulciano in het gouden avondlicht."),
    ("2026-09-24", "Uitchecken en roadtrip naar Parma",
     ["check_out", "swimming", "driving", "check_in", "city"],
     "Rustig ontwaken, misschien nog zwemmen, dan uitchecken. 2,5 uur naar Parma, "
     "hotel inchecken, samen uiteten."),
    ("2026-09-25", "Parma en de sleeper terug",
     ["driving", "car_return", "city", "night_train", "travel_day"],
     "Anderhalf uur naar Milaan, auto terug rond 14u. Centraal station verkennen, "
     "7 min naar Porta Garibaldi. Trein om 16.00, dus 15.30 met de koffers klaarstaan."),
    ("2026-09-26", "Aankomst Brussel en Brugge",
     ["travel_day", "arrival"],
     "11.42 in Brussel-Zuid. Trein naar Brugge om 11.51, 12.03 of 12.51. "
     "Jolien haalt ons op aan het station."),
]


def build():
    items = [
        {
            "id": item_id,
            "name": name,
            "category": category,
            "tags": tags,
            "suggests": suggests,
            "always": always,
            "notes": notes,
        }
        for item_id, name, category, tags, suggests, always, notes in ITEMS
    ]
    trip = {
        "id": "toscane_2026",
        "name": "Toscane 2026",
        "start": DAYS[0][0],
        "end": DAYS[-1][0],
        "notes": "European Sleeper naar Milaan, huurauto vanuit Guardistallo, sleeper terug.",
        "days": [
            {"date": date, "title": title, "tags": tags, "notes": notes}
            for date, title, tags, notes in DAYS
        ],
        "packing": [],
        "dismissed": [],
    }
    return store.normalize_data(
        {"version": store.SCHEMA_VERSION, "active_trip": trip["id"],
         "items": items, "trips": [trip]}
    )


def main():
    data = build()
    dangling = store.dangling_suggestions(data)
    if dangling:
        raise SystemExit("suggestion links point at unknown items: %r" % (dangling,))
    target = os.path.join(ROOT, "app", "seed", "default.json")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print("wrote %s: %d items, %d trips, %d days"
          % (target, len(data["items"]), len(data["trips"]),
             len(data["trips"][0]["days"])))


if __name__ == "__main__":
    main()
