from datetime import date, datetime

from homehub.timeutil import LONDON, event_window, iso, local_midnight


def test_iso_offset():
    assert iso(datetime(2026, 10, 22, 8, 42, tzinfo=LONDON)) == "2026-10-22T08:42:00+01:00"
    assert iso(datetime(2026, 10, 26, 9, 0, tzinfo=LONDON)) == "2026-10-26T09:00:00+00:00"


def test_iso_drops_microseconds_and_converts_utc():
    dt = datetime(2026, 7, 1, 12, 0, 0, 500, tzinfo=LONDON).astimezone()
    assert iso(dt) == "2026-07-01T12:00:00+01:00"


def test_local_midnight():
    assert iso(local_midnight(date(2026, 10, 25))) == "2026-10-25T00:00:00+01:00"


def test_window():
    start, end = event_window(datetime(2026, 10, 22, 8, 42, tzinfo=LONDON))
    assert iso(start) == "2026-10-22T00:00:00+01:00"
    assert iso(end) == "2026-11-05T00:00:00+00:00"
