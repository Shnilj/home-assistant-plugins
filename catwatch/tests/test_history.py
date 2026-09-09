import json
from datetime import datetime, timedelta

from app.history import EventLog


def _log(tmp_path):
    snap = tmp_path / "snap"
    crop = tmp_path / "crop"
    snap.mkdir()
    crop.mkdir()
    return EventLog(str(tmp_path / "ev.json"), str(snap), crop_dir=str(crop)), snap, crop


def _now():
    return datetime.now().astimezone().isoformat()


def test_crud(tmp_path):
    log, _, _ = _log(tmp_path)
    eid = log.add("Ellie", "eating", "Bowl", "s.jpg", _now(), crop="c.jpg")
    assert log.get(eid)["duration"] is None
    assert log.set_duration(eid, 30.4) and log.get(eid)["duration"] == 30
    assert log.set_fields(eid, cat="Milo") and log.get(eid)["cat"] == "Milo"
    assert log.remove(eid) and log.get(eid) is None
    assert log.remove("missing") is False


def test_prune_by_age_keeps_recent(tmp_path):
    log, snap, _ = _log(tmp_path)
    (snap / "old.jpg").write_bytes(b"x")
    old_ts = (datetime.now().astimezone() - timedelta(hours=30)).isoformat()
    log.add("Ellie", "eating", "Bowl", "old.jpg", old_ts)
    log.add("Ellie", "eating", "Bowl", None, _now())
    assert log.prune(24 * 3600) == 1
    assert len(log.list()) == 1
    assert not (snap / "old.jpg").exists()  # crop/snapshot deleted with the event


def test_id_backfill(tmp_path):
    path = tmp_path / "ev.json"
    (tmp_path / "snap").mkdir()
    path.write_text(json.dumps([{"ts": _now(), "cat": "Ellie", "action": "eating"}]))
    log = EventLog(str(path), str(tmp_path / "snap"))
    assert log.list()[0].get("id")
