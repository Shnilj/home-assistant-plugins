from datetime import date

from app.stats import DailyStats


def _stats(tmp_path):
    return DailyStats(str(tmp_path / "stats.json"))


def test_add_and_count(tmp_path):
    s = _stats(tmp_path)
    s.add_event("Ellie", "eating")
    s.add_event("Ellie", "eating")
    s.add_duration("Ellie", "eating", 120)
    assert s.count("Ellie", "eating") == 2
    assert s.week_totals("Ellie")["eat_sec"] == 120


def test_adjust_moves_and_clamps(tmp_path):
    s = _stats(tmp_path)
    day = date.today().isoformat()
    s.add_event("Milo", "eating")
    s.adjust(day, "Milo", "eating", d_count=-1, d_seconds=-30)  # clamps at 0
    assert s.count("Milo", "eating") == 0
    assert s.week_totals("Milo")["eat_sec"] == 0


def test_last_days_shape(tmp_path):
    s = _stats(tmp_path)
    s.add_event("Ellie", "eating")
    ld = s.last_days(7, ["Ellie", "Milo"])
    assert len(ld) == 7
    assert ld[-1]["cats"]["Ellie"]["meals"] == 1
    assert ld[0]["cats"]["Milo"]["meals"] == 0


def test_version_increments(tmp_path):
    s = _stats(tmp_path)
    v0 = s.version
    s.add_event("Ellie", "drinking")
    assert s.version > v0
