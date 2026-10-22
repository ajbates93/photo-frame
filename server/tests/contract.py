"""Shape checker for the State object in docs/api-contract.md."""
from __future__ import annotations

from datetime import datetime

CONDS = {"sun", "partly", "cloud", "rain", "snow", "fog", "storm", "night"}
ASSIGNEES = {"alex", "vicky", "any"}
SESSION_STATES = {"working", "waiting", "done"}
SCREEN_MODES = {"on", "dim", "off"}


def _fail(path: str, msg: str):
    raise AssertionError(f"{path}: {msg}")


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_keys(obj, path: str, spec: dict) -> None:
    if not isinstance(obj, dict):
        _fail(path, f"expected object, got {type(obj).__name__}")
    missing = set(spec) - set(obj)
    if missing:
        _fail(path, f"missing keys {sorted(missing)}")
    extra = set(obj) - set(spec)
    if extra:
        _fail(path, f"unexpected keys {sorted(extra)}")
    for key, check in spec.items():
        check(obj[key], f"{path}.{key}")


def s(v, p):
    if not isinstance(v, str):
        _fail(p, f"expected string, got {v!r}")


def num(v, p):
    if not _is_num(v):
        _fail(p, f"expected number, got {v!r}")


def boolean(v, p):
    if not isinstance(v, bool):
        _fail(p, f"expected boolean, got {v!r}")


def iso_str(v, p):
    s(v, p)
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        _fail(p, f"not ISO 8601: {v!r}")
    if dt.tzinfo is None:
        _fail(p, f"ISO string has no offset: {v!r}")


def nullable(check):
    def inner(v, p):
        if v is not None:
            check(v, p)

    return inner


def enum(values):
    def inner(v, p):
        if v not in values:
            _fail(p, f"{v!r} not in {sorted(values)}")

    return inner


def array_of(check):
    def inner(v, p):
        if not isinstance(v, list):
            _fail(p, f"expected array, got {type(v).__name__}")
        for i, item in enumerate(v):
            check(item, f"{p}[{i}]")

    return inner


def obj(spec):
    return lambda v, p: _check_keys(v, p, spec)


def volume(v, p):
    num(v, p)
    if not 0 <= v <= 100:
        _fail(p, f"volume out of range: {v!r}")


def literal(expected):
    def inner(v, p):
        if v != expected:
            _fail(p, f"expected {expected!r}, got {v!r}")

    return inner


_pct = obj({"pct": num, "resetsAt": iso_str})

STATE_SPEC = {
    "generatedAt": iso_str,
    "timezone": literal("Europe/London"),
    "people": array_of(obj({"id": s, "name": s, "color": s})),
    "calendars": array_of(obj({"id": s, "label": s, "color": s})),
    "events": array_of(obj({
        "id": s, "calendarId": s, "title": s, "start": iso_str, "end": iso_str,
        "allDay": boolean, "location": nullable(s), "travelMins": nullable(num),
    })),
    "weather": nullable(obj({
        "location": s, "temp": num, "cond": enum(CONDS), "label": s, "hi": num, "lo": num,
        "summary": s, "sunrise": iso_str, "sunset": iso_str,
        "hourly": array_of(obj({
            "time": iso_str, "temp": num, "cond": enum(CONDS), "rainPct": num,
        })),
    })),
    "photos": array_of(obj({
        "id": s, "url": s, "takenAt": nullable(iso_str), "place": nullable(s),
        "width": num, "height": num,
    })),
    "shopping": obj({
        "items": array_of(obj({"id": s, "text": s, "checked": boolean})),
        "syncedAt": nullable(iso_str),
        "stale": boolean,
    }),
    "tasks": array_of(obj({
        "id": s, "title": s, "assignee": enum(ASSIGNEES), "due": nullable(iso_str),
        "done": boolean,
    })),
    "plugs": array_of(obj({
        "id": s, "name": s, "room": s, "on": boolean, "reachable": boolean,
        "confirm": boolean, "hidden": boolean,
    })),
    "speaker": nullable(obj({
        "name": s, "reachable": boolean, "playing": boolean, "title": nullable(s),
        "artist": nullable(s), "volume": volume,
    })),
    "claude": obj({
        "sessions": array_of(obj({
            "id": s, "project": s, "state": enum(SESSION_STATES), "since": iso_str,
        })),
        "usage": nullable(obj({"plan": s, "session": _pct, "weekly": _pct})),
    }),
    "screen": obj({"mode": enum(SCREEN_MODES)}),
}


def assert_state_shape(state) -> None:
    """Raise AssertionError (with a path) if `state` deviates from the contract."""
    _check_keys(state, "state", STATE_SPEC)
