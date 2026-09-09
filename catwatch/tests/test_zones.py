from app import zones


class S:
    zone_coverage = 0.3
    require_lean_in = True


FOOD = {"id": "z1", "name": "Food", "type": "food", "rect": [100, 100, 80, 60]}


def test_cat_leaning_into_bowl_is_picked():
    cat = [90, 60, 90, 90]  # overlaps the zone, top (60) rises above zone top (100)
    assert zones.coverage(cat, FOOD["rect"]) > 0.3
    best, cov = zones.pick_zone(cat, [FOOD], S())
    assert best is not None and best["id"] == "z1" and cov > 0.3


def test_cat_beside_bowl_rejected():
    assert zones.pick_zone([400, 400, 30, 30], [FOOD], S())[0] is None


def test_non_leaning_cat_rejected_when_required():
    low = [100, 130, 80, 40]  # sits low, not rising above the zone
    assert zones.pick_zone(low, [FOOD], S())[0] is None


def test_detect_region_none_without_zones():
    assert zones.detect_region([], (480, 640, 3)) is None


def test_detect_region_spans_zones():
    r = zones.detect_region([FOOD], (480, 640, 3))
    assert r and r[2] > 80 and r[3] > 60  # padded outward
