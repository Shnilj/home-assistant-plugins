from app import config


def test_slugify():
    assert config.slugify("Ellie") == "ellie"
    assert config.slugify("Mr. Whiskers 2") == "mr_whiskers_2"


def test_zone_validation_and_ids():
    config.save_zones([
        {"type": "food", "rect": [10, 10, 50, 40]},
        {"type": "water", "rect": [80, 10, 30, 30], "name": "Fountain"},
        {"type": "bogus", "rect": [0, 0, 20, 20]},   # dropped: bad type
        {"type": "food", "rect": [0, 0, 2, 2]},       # dropped: too small
    ])
    z = config.load_zones()
    assert [x["type"] for x in z] == ["food", "water"]
    assert all(x["id"] for x in z)
    assert len({x["id"] for x in z}) == 2


def test_legacy_roi_migration(tmp_path):
    import json
    with open(config.SETTINGS_PATH, "w") as fh:
        json.dump({"roi": [5, 6, 40, 40]}, fh)
    z = config.load_zones()
    assert len(z) == 1 and z[0]["type"] == "food"


def test_dwell_and_cooldown():
    s = config.load_settings()
    assert s.dwell_for("drinking") == s.drink_dwell_seconds
    assert s.dwell_for("eating") == s.eating_dwell_seconds
    assert s.cooldown_for("eating") == s.meal_cooldown_minutes
    assert s.cooldown_for("drinking") == s.drink_cooldown_minutes
