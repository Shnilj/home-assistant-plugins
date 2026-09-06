"""Zone geometry: how a detected cat relates to the food/water zones.

A zone is a dict {id, name, type, rect:[x, y, w, h]} in full-frame pixels.
"""
from __future__ import annotations


def _intersection_area(a, b) -> int:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(ax, bx)
    iy = max(ay, by)
    ix2 = min(ax + aw, bx + bw)
    iy2 = min(ay + ah, by + bh)
    if ix2 <= ix or iy2 <= iy:
        return 0
    return (ix2 - ix) * (iy2 - iy)


def coverage(cat_bbox, zone_rect) -> float:
    """Fraction of the zone covered by the cat's bounding box (0-1).

    Relative to the zone, so a bowl drifting a little inside a slightly larger
    zone doesn't change the result much.
    """
    zw, zh = zone_rect[2], zone_rect[3]
    area = zw * zh
    if area <= 0:
        return 0.0
    return _intersection_area(cat_bbox, zone_rect) / float(area)


def leans_in(cat_bbox, zone_rect) -> bool:
    """True if the cat's body rises above the top of the zone — i.e. it's bent
    over the bowl (head down) rather than sitting entirely within a large zone."""
    cat_top = cat_bbox[1]
    zone_top = zone_rect[1]
    zone_h = zone_rect[3]
    # Allow the head to dip a bit below the rim before we call it "not leaning".
    return cat_top <= zone_top + 0.25 * zone_h


def pick_zone(cat_bbox, zones, settings):
    """Return (zone, coverage) for the best qualifying zone, or (None, 0.0).

    A zone qualifies when the cat covers at least ``zone_coverage`` of it and
    (optionally) is leaning in. The zone with the highest coverage wins.
    """
    best = None
    best_cov = 0.0
    for z in zones:
        cov = coverage(cat_bbox, z["rect"])
        if cov < settings.zone_coverage:
            continue
        if settings.require_lean_in and not leans_in(cat_bbox, z["rect"]):
            continue
        if cov > best_cov:
            best, best_cov = z, cov
    return best, best_cov


def detect_region(zones, frame_shape, pad_frac: float = 0.6):
    """Bounding box (x, y, w, h) covering all zones, padded outward so an
    approaching cat is seen. Returns None (whole frame) when there are no zones.
    """
    if not zones:
        return None
    xs0 = [z["rect"][0] for z in zones]
    ys0 = [z["rect"][1] for z in zones]
    xs1 = [z["rect"][0] + z["rect"][2] for z in zones]
    ys1 = [z["rect"][1] + z["rect"][3] for z in zones]
    x0, y0, x1, y1 = min(xs0), min(ys0), max(xs1), max(ys1)
    padx = int((x1 - x0) * pad_frac)
    pady = int((y1 - y0) * pad_frac)
    h, w = frame_shape[:2]
    x0 = max(0, x0 - padx)
    y0 = max(0, y0 - pady)
    x1 = min(w, x1 + padx)
    y1 = min(h, y1 + pady)
    return [x0, y0, x1 - x0, y1 - y0]
