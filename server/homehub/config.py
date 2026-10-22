from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PLACEHOLDER = "CHANGE_ME"
SERVER_DIR = Path(__file__).resolve().parent.parent


class ConfigError(Exception):
    pass


@dataclass
class Person:
    id: str
    name: str
    color: str
    ics_url: str | None = field(default=None, repr=False)


@dataclass
class CalendarCfg:
    id: str
    label: str
    color: str
    ics_url: str | None = field(default=None, repr=False)


@dataclass
class CalendarSettings:
    default_travel_mins: int = 15


@dataclass
class Location:
    name: str
    lat: float
    lon: float


@dataclass
class Screen:
    dim_at: str = "22:00"
    off_at: str = "23:00"
    on_at: str = "07:00"
    idle_minutes: int = 30
    wake_minutes: int = 10


@dataclass
class Keep:
    list_title: str
    email: str = field(repr=False)


@dataclass
class Drive:
    folder_id: str = field(repr=False)
    service_account_file: str = field(repr=False)


@dataclass
class PlugCfg:
    host: str
    room: str
    name: str | None = None
    confirm: bool = False
    hidden: bool = False


@dataclass
class Tapo:
    username: str
    password: str = field(repr=False)


@dataclass
class SpeakerCfg:
    name: str


DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _hhmm(value: Any, what: str) -> tuple[int, int]:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        raise ConfigError(f"invalid {what} in [[routines]]: expected HH:MM, got {value!r}")
    hh, mm = value[:2], value[3:]
    if not (hh.isdigit() and mm.isdigit() and int(hh) < 24 and int(mm) < 60):
        raise ConfigError(f"invalid {what} in [[routines]]: expected HH:MM, got {value!r}")
    return int(hh), int(mm)


@dataclass
class Routine:
    """A recurring weekly outing the weather hint is tailored to (London wall time)."""

    label: str
    days: list[str]
    start: str
    end: str

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label.strip():
            raise ConfigError("invalid [[routines]]: label must be a non-empty string")
        if (
            not isinstance(self.days, list)
            or not self.days
            or any(d not in DAYS for d in self.days)
        ):
            raise ConfigError(
                f"invalid [[routines]] {self.label!r}: days must be a non-empty list of "
                f"{', '.join(DAYS)}"
            )
        if _hhmm(self.start, "start") >= _hhmm(self.end, "end"):
            raise ConfigError(f"invalid [[routines]] {self.label!r}: start must be before end")


@dataclass
class Config:
    shared_secret: str = field(repr=False)
    people: list[Person] = field(default_factory=list)
    calendars: list[CalendarCfg] = field(default_factory=list)
    calendar: CalendarSettings = field(default_factory=CalendarSettings)
    location: Location | None = None
    intervals: dict[str, float] = field(default_factory=dict)
    screen: Screen = field(default_factory=Screen)
    keep: Keep | None = None
    drive: Drive | None = None
    plugs: list[PlugCfg] = field(default_factory=list)
    tapo: Tapo | None = None
    speaker: SpeakerCfg | None = None
    routines: list[Routine] = field(default_factory=list)
    data_dir: Path = field(default_factory=lambda: SERVER_DIR / "secrets")


INTERVAL_KEYS = (
    "events", "weather", "photos", "shopping", "tasks", "plugs", "speaker", "claude", "screen",
)
MIN_INTERVAL_S = 5


def _intervals(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise ConfigError("[intervals] must be a table of seconds")
    out = {}
    for key, value in raw.items():
        if key not in INTERVAL_KEYS:
            raise ConfigError(
                f"unknown key {key!r} in [intervals] (known: {', '.join(INTERVAL_KEYS)})"
            )
        if (
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < MIN_INTERVAL_S
        ):
            raise ConfigError(
                f"[intervals] {key} must be a number of seconds, at least {MIN_INTERVAL_S}"
            )
        out[key] = value
    return out


def _build(cls: type, data: dict[str, Any], where: str):
    try:
        return cls(**data)
    except TypeError as e:
        raise ConfigError(f"invalid [{where}] in config: {e}") from e


def load_config(path: str | Path) -> Config:
    p = Path(path)
    try:
        with p.open("rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError as e:
        raise ConfigError(f"config file not found: {p}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"config is not valid TOML: {e}") from e

    secret = raw.get("shared_secret")
    if not isinstance(secret, str) or not secret or secret == PLACEHOLDER:
        raise ConfigError("shared_secret is missing or still CHANGE_ME")

    loc = raw.get("location")
    keep = raw.get("keep")
    drive = raw.get("drive")
    tapo = raw.get("tapo")
    speaker = raw.get("speaker")
    extra = {}
    if "data_dir" in raw:
        if not isinstance(raw["data_dir"], str) or not raw["data_dir"]:
            raise ConfigError("data_dir must be a non-empty string")
        extra["data_dir"] = (SERVER_DIR / raw["data_dir"]).resolve()
    return Config(
        shared_secret=secret,
        people=[_build(Person, d, "people") for d in raw.get("people", [])],
        calendars=[_build(CalendarCfg, d, "calendars") for d in raw.get("calendars", [])],
        calendar=_build(CalendarSettings, raw.get("calendar", {}), "calendar"),
        location=_build(Location, loc, "location") if loc else None,
        intervals=_intervals(raw.get("intervals", {})),
        screen=_build(Screen, raw.get("screen", {}), "screen"),
        keep=_build(Keep, keep, "keep") if keep else None,
        drive=_build(Drive, drive, "drive") if drive else None,
        plugs=[_build(PlugCfg, d, "plugs") for d in raw.get("plugs", [])],
        tapo=_build(Tapo, tapo, "tapo") if tapo else None,
        speaker=_build(SpeakerCfg, speaker, "speaker") if speaker else None,
        routines=[_build(Routine, d, "routines") for d in raw.get("routines", [])],
        **extra,
    )
