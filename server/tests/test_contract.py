import copy

import pytest

from tests.contract import assert_state_shape

VALID = {
    "generatedAt": "2026-10-22T08:42:00+01:00",
    "timezone": "Europe/London",
    "people": [{"id": "alex", "name": "Alex", "color": "#fff"}],
    "calendars": [{"id": "c", "label": "C", "color": "#000"}],
    "events": [{
        "id": "e", "calendarId": "c", "title": "T", "start": "2026-10-22T09:00:00+01:00",
        "end": "2026-10-22T10:00:00+01:00", "allDay": False, "location": None, "travelMins": 5,
    }],
    "weather": {
        "location": "X", "temp": 12.5, "cond": "rain", "label": "Rain", "hi": 14, "lo": 8,
        "summary": "s", "sunrise": "2026-10-22T07:20:00+01:00",
        "sunset": "2026-10-22T17:40:00+01:00",
        "hourly": [{"time": "2026-10-22T08:00:00+01:00", "temp": 12, "cond": "night", "rainPct": 40}],
    },
    "photos": [{"id": "p", "url": "/api/photos/p", "takenAt": None, "place": None,
                "width": 1280, "height": 800}],
    "shopping": {"items": [{"id": "i", "text": "milk", "checked": False}],
                 "syncedAt": "2026-10-22T08:00:00+01:00", "stale": False},
    "tasks": [{"id": "t", "title": "T", "assignee": "any", "due": None, "done": False}],
    "plugs": [{"id": "p", "name": "Lamp", "room": "R", "on": True, "reachable": True,
               "confirm": False, "hidden": False}],
    "speaker": {"name": "S", "reachable": True, "playing": False, "title": None,
                "artist": None, "volume": 30},
    "claude": {"sessions": [{"id": "s", "project": "p", "state": "working",
                             "since": "2026-10-22T08:00:00+01:00"}],
               "usage": {"plan": "max", "session": {"pct": 10, "resetsAt": "2026-10-22T12:00:00+01:00"},
                         "weekly": {"pct": 20, "resetsAt": "2026-10-26T12:00:00+00:00"}}},
    "screen": {"mode": "dim"},
}


def mutated(fn):
    s = copy.deepcopy(VALID)
    fn(s)
    return s


def test_valid_state_passes():
    assert_state_shape(VALID)


def test_nulls_pass():
    assert_state_shape(mutated(lambda s: s.update(weather=None, speaker=None)))


@pytest.mark.parametrize("name,fn", [
    ("missing key", lambda s: s.pop("tasks")),
    ("extra key", lambda s: s.update(bogus=1)),
    ("wrong type", lambda s: s["events"][0].update(allDay="no")),
    ("bad cond", lambda s: s["weather"].update(cond="hail")),
    ("bad hourly cond", lambda s: s["weather"]["hourly"][0].update(cond="x")),
    ("bad screen mode", lambda s: s["screen"].update(mode="sleep")),
    ("bad assignee", lambda s: s["tasks"][0].update(assignee="bob")),
    ("bad session state", lambda s: s["claude"]["sessions"][0].update(state="idle")),
    ("naive time", lambda s: s.update(generatedAt="2026-10-22T08:42:00")),
    ("bool as number", lambda s: s["plugs"][0].update(on=1)),
    ("volume range", lambda s: s["speaker"].update(volume=101)),
    ("nested missing", lambda s: s["claude"]["usage"]["weekly"].pop("pct")),
    ("wrong timezone", lambda s: s.update(timezone="UTC")),
    ("shopping stale type", lambda s: s["shopping"].update(stale=None)),
], ids=lambda v: v if isinstance(v, str) else "")
def test_invalid_state_fails(name, fn):
    with pytest.raises(AssertionError):
        assert_state_shape(mutated(fn))
