from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from homehub.config import Location, Routine
from homehub.hub import Hub
from homehub.providers.weather import WeatherProvider, summary, wmo_to_cond
from homehub.timeutil import LONDON
from tests.conftest import FIXED_NOW
from tests.contract import assert_state_shape

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "open-meteo.json").read_text())
CLOCK = json.loads(
    (Path(__file__).parent / "fixtures" / "open-meteo-clock-change.json").read_text()
)
URL = "https://api.open-meteo.com/v1/forecast"


@pytest.fixture
def wcfg(cfg):
    return replace(cfg, location=Location(name="Test City", lat=51.5074, lon=-0.1278))


@pytest.fixture
async def http():
    async with httpx.AsyncClient() as c:
        yield c


@respx.mock
async def test_refresh_matches_contract(wcfg, http, hub):
    route = respx.get(URL).respond(json=FIXTURE)
    w = await WeatherProvider(wcfg, http).refresh(FIXED_NOW)
    state = hub.empty_state()
    state["weather"] = w
    assert_state_shape(state)
    q = route.calls[0].request.url.params
    assert q["timeformat"] == "unixtime"
    assert q["timezone"] == "Europe/London" and q["forecast_days"] == "2"
    assert q["current"] == "temperature_2m,weather_code,is_day"
    assert q["hourly"] == (
        "temperature_2m,weather_code,precipitation_probability,"
        "wind_gusts_10m,apparent_temperature"
    )
    assert q["daily"] == "temperature_2m_max,temperature_2m_min,sunrise,sunset"
    assert w["location"] == "Test City"
    assert (w["temp"], w["cond"], w["label"]) == (11, "cloud", "Cloudy")
    assert (w["hi"], w["lo"]) == (15, 8)
    assert w["sunrise"] == "2026-10-22T07:12:00+01:00"
    assert w["sunset"] == "2026-10-22T17:45:00+01:00"


@respx.mock
async def test_hourly_starts_at_current_hour_with_int_temps(wcfg, http):
    respx.get(URL).respond(json=FIXTURE)
    w = await WeatherProvider(wcfg, http).refresh(FIXED_NOW)
    h = w["hourly"]
    assert h[0]["time"] == "2026-10-22T08:00:00+01:00"
    assert len(h) >= 6
    assert all(isinstance(e["temp"], int) and isinstance(e["rainPct"], int) for e in h)
    assert h[0]["temp"] == 10
    assert h[8]["time"] == "2026-10-22T16:00:00+01:00" and h[8]["rainPct"] == 70


@pytest.mark.parametrize(
    "code,is_day,cond",
    [(0, True, "sun"), (0, False, "night"), (2, True, "partly"), (3, True, "cloud"),
     (45, True, "fog"), (61, True, "rain"), (82, True, "rain"), (73, True, "snow"),
     (95, True, "storm")],
)
def test_wmo_to_cond(code, is_day, cond):
    assert wmo_to_cond(code, is_day) == cond


def _hourly(rain: dict[int, int] | None = None, gust: dict[int, int] | None = None,
            feels: dict[int, int] | None = None, day=(2026, 10, 22), hours=range(24)):
    rain, gust, feels = rain or {}, gust or {}, feels or {}
    return [
        {"time": datetime(*day, h, tzinfo=LONDON).isoformat(), "temp": 10,
         "cond": "cloud", "rainPct": rain.get(h, 0),
         "gust": gust.get(h, 15), "feels": feels.get(h, 9)}
        for h in hours
    ]


ROUTINES = [
    Routine("Early run", ["mon", "wed", "fri"], "06:30", "07:30"),
    Routine("Swim class", ["mon", "wed", "thu", "fri"], "10:00", "11:30"),
    Routine("Football", ["mon", "tue", "wed"], "16:00", "16:45"),
]
TUE = (2026, 10, 20)
WED = (2026, 10, 21)
FRI = (2026, 10, 23)
SAT = (2026, 10, 24)


def at(day, h, m=0):
    return datetime(*day, h, m, tzinfo=LONDON)


def test_routine_rain_mentions_swim_class():
    s = summary(_hourly({10: 70}, day=WED), at(WED, 9), ROUTINES)
    assert s == "Rain likely for Swim class (10am) \u2014 take a coat."


def test_routine_rain_in_any_overlapping_hour():
    s = summary(_hourly({11: 50}, day=WED), at(WED, 9), ROUTINES)
    assert s.startswith("Rain likely for Swim class")
    # 12:00 starts after the 11:30 end, so it does not overlap
    assert summary(_hourly({12: 90}, day=WED), at(WED, 9), ROUTINES) == (
        "Dry for Swim class (10am)."
    )


def test_day_without_routine_skips_it():
    s = summary(_hourly({10: 90, 16: 80}, day=TUE), at(TUE, 9), ROUTINES)
    assert "Football (4pm)" in s and "Swim" not in s


def test_after_routine_ended_next_is_following_one():
    s = summary(_hourly({10: 90}, day=WED), at(WED, 11, 31), ROUTINES)
    assert s == "Dry for Football (4pm)."


def test_routine_in_progress_is_still_next():
    s = summary(_hourly({10: 90}, day=WED), at(WED, 11, 29), ROUTINES)
    assert s.startswith("Rain likely for Swim class")


def test_friday_after_routines_uses_general_forecast():
    s = summary(_hourly({20: 70}, day=FRI), at(FRI, 15), ROUTINES)
    assert s == "Rain from 8pm."


def test_saturday_uses_general_forecast():
    assert summary(_hourly({}, day=SAT), at(SAT, 9), ROUTINES) == "Dry rest of the day."


def test_very_windy_at_football():
    s = summary(_hourly({}, {16: 65}, day=WED), at(WED, 13), ROUTINES)
    assert s == "Very windy at Football (4pm)."


def test_windy_threshold():
    assert summary(_hourly({}, {16: 40}, day=WED), at(WED, 13), ROUTINES) == (
        "Windy at Football (4pm)."
    )
    assert summary(_hourly({}, {16: 39}, day=WED), at(WED, 13), ROUTINES).startswith("Dry")


def test_cold_reports_rounded_minimum():
    s = summary(_hourly({}, None, {6: 2.4, 7: 5}, day=WED), at(WED, 5, 30), ROUTINES)
    assert s == "Cold (2\u00b0) for Early run (6:30am)."
    assert summary(_hourly({}, None, {6: 3}, day=WED), at(WED, 5, 30), ROUTINES).startswith(
        "Cold (3"
    )
    assert summary(_hourly({}, None, {6: 3.6}, day=WED), at(WED, 5, 30), ROUTINES).startswith(
        "Dry"
    )


def test_two_conditions_combine_in_priority_order():
    s = summary(_hourly({16: 60}, {16: 45}, day=WED), at(WED, 13), ROUTINES)
    assert s == "Rain and wind for Football (4pm)."
    s = summary(_hourly({16: 60}, {16: 45}, {16: 1}, day=WED), at(WED, 13), ROUTINES)
    assert s == "Rain and wind for Football (4pm)."  # cold dropped: max two
    s = summary(_hourly({}, {16: 45}, {16: 1}, day=WED), at(WED, 13), ROUTINES)
    assert s == "Windy and cold (1\u00b0) for Football (4pm)."
    s = summary(_hourly({16: 60}, {}, {16: 1}, day=WED), at(WED, 13), ROUTINES)
    assert s == "Rain and cold (1\u00b0) for Football (4pm)."


def test_summary_sentences_are_short():
    for rain in ({10: 70}, {}):
        s = summary(_hourly(rain, {10: 70}, {10: 0}, day=WED), at(WED, 9), ROUTINES)
        assert all(len(x) < 70 for x in s.split(". "))


def test_general_rain_from():
    assert summary(_hourly({16: 70}), FIXED_NOW) == "Rain from 4pm."


def test_general_showers_clearing():
    s = summary(_hourly({8: 70, 9: 60, 10: 55}), FIXED_NOW)
    assert s == "Showers this morning, clearing by 11am."


def test_general_dry_rest_of_day_ignores_past_rain():
    assert summary(_hourly({}), FIXED_NOW) == "Dry rest of the day."
    assert summary(_hourly({6: 90}), FIXED_NOW) == "Dry rest of the day."


def test_general_evening_overnight():
    now = at((2026, 10, 22), 19)
    assert summary(_hourly({22: 80}), now) == "Rain overnight."
    assert summary(_hourly({}), now) == "Dry tonight."


def test_general_windy_appended():
    assert summary(_hourly({16: 70}, {14: 45}), FIXED_NOW) == (
        "Rain from 4pm. Windy this afternoon."
    )
    assert summary(_hourly({}, {14: 62}), FIXED_NOW) == (
        "Dry rest of the day. Very windy this afternoon."
    )


def test_routines_default_empty():
    assert summary(_hourly({16: 70}), FIXED_NOW, []) == "Rain from 4pm."


@respx.mock
async def test_http_500_raises_and_hub_keeps_previous(wcfg, http):
    hub = Hub(wcfg, now=lambda: FIXED_NOW)
    hub.register("weather", WeatherProvider(wcfg, http), 1800)
    respx.get(URL).respond(json=FIXTURE)
    assert await hub.refresh_one("weather") is True
    before = hub.get_state()["weather"]
    assert before is not None
    respx.get(URL).respond(500)
    assert await hub.refresh_one("weather") is False
    assert hub.get_state()["weather"] == before
    with pytest.raises(RuntimeError, match=r"^weather http 500$") as exc:
        await WeatherProvider(wcfg, http).refresh(FIXED_NOW)
    # Nothing that could print the URL (with the home lat/lon) is attached.
    assert exc.value.__cause__ is None and exc.value.__suppress_context__


@respx.mock
async def test_http_error_never_logs_the_location(wcfg, http, caplog):
    import logging

    hub = Hub(wcfg, now=lambda: FIXED_NOW)
    hub.register("weather", WeatherProvider(wcfg, http), 1800)
    respx.get(URL).respond(503)
    with caplog.at_level(logging.DEBUG, logger="homehub"):
        assert await hub.refresh_one("weather") is False
    assert "51.5" not in caplog.text and "-0.12" not in caplog.text


@respx.mock
async def test_clock_change_hourly_unique_and_ordered(wcfg, http):
    respx.get(URL).respond(json=CLOCK)
    now = datetime(2026, 10, 25, 1, 30, tzinfo=UTC).astimezone(LONDON)
    assert now.utcoffset().total_seconds() == 0
    w = await WeatherProvider(wcfg, http).refresh(now)
    times = [e["time"] for e in w["hourly"]]
    assert times[0] == "2026-10-25T01:00:00+00:00"
    assert len(set(times)) == len(times)
    instants = [datetime.fromisoformat(t).timestamp() for t in times]
    assert instants == sorted(instants) and len(set(instants)) == len(instants)
    assert len(times) >= 6
    # the earlier (BST) 01:00 is dropped, the GMT one kept
    assert "2026-10-25T01:00:00+01:00" not in times


@respx.mock
async def test_clock_change_both_repeated_hours_present_from_midnight(wcfg, http):
    respx.get(URL).respond(json=CLOCK)
    now = datetime(2026, 10, 25, 0, 10, tzinfo=LONDON)
    w = await WeatherProvider(wcfg, http).refresh(now)
    times = [e["time"] for e in w["hourly"][:4]]
    assert times == [
        "2026-10-25T00:00:00+01:00", "2026-10-25T01:00:00+01:00",
        "2026-10-25T01:00:00+00:00", "2026-10-25T02:00:00+00:00",
    ]
    assert w["sunrise"] == "2026-10-25T06:18:00+00:00"
    assert w["hi"] == 14


@respx.mock
async def test_near_midnight_still_has_six_hours(wcfg, http):
    respx.get(URL).respond(json=FIXTURE)
    now = datetime(2026, 10, 22, 23, 30, tzinfo=LONDON)
    w = await WeatherProvider(wcfg, http).refresh(now)
    assert w["hourly"][0]["time"] == "2026-10-22T23:00:00+01:00"
    assert len(w["hourly"]) >= 6


@respx.mock
async def test_refresh_sends_routine_hint_and_hides_extra_hourly_fields(wcfg, http):
    respx.get(URL).respond(json=FIXTURE)
    cfg = replace(wcfg, routines=[
        Routine("Afternoon walk", ["thu"], "14:00", "15:00"),
    ])
    w = await WeatherProvider(cfg, http).refresh(FIXED_NOW)
    assert w["summary"] == "Rain likely for Afternoon walk (2pm) \u2014 take a coat."
    assert all(set(e) == {"time", "temp", "cond", "rainPct"} for e in w["hourly"])


@respx.mock
async def test_clock_change_sunday_uses_general_forecast(wcfg, http):
    respx.get(URL).respond(json=CLOCK)
    cfg = replace(wcfg, routines=ROUTINES)
    now = datetime(2026, 10, 25, 1, 30, tzinfo=UTC).astimezone(LONDON)
    w = await WeatherProvider(cfg, http).refresh(now)
    assert w["summary"] == "Dry rest of the day."
