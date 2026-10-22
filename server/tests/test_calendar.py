from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import respx

from homehub.app import configure_logging
from homehub.config import CalendarCfg, CalendarSettings
from homehub.hub import Hub
from homehub.providers.calendar import CalendarProvider, is_online, summarise
from tests.conftest import FIXED_NOW
from tests.contract import assert_state_shape

FIXTURES = Path(__file__).parent / "fixtures"
ALEX_ICS = (FIXTURES / "alex.ics").read_bytes()
FAMILY_ICS = (FIXTURES / "family-utc.ics").read_bytes()
ALEX_URL = "https://example.invalid/secret-alex/basic.ics"
FAMILY_URL = "https://example.invalid/secret-family/basic.ics"


@pytest.fixture
def ccfg(cfg):
    return replace(cfg, calendars=[
        CalendarCfg(id="alex", label="Alex", color="#111111", ics_url=ALEX_URL),
        CalendarCfg(id="family", label="Family", color="#222222", ics_url=FAMILY_URL),
    ])


@pytest.fixture
def app_logging():
    """Apply the app's logging setup, restoring logger levels afterwards."""
    names = ("httpx", "httpcore")
    saved = {n: logging.getLogger(n).level for n in names}
    configure_logging()
    yield
    for n, level in saved.items():
        logging.getLogger(n).setLevel(level)


@pytest.fixture
async def http():
    async with httpx.AsyncClient() as c:
        yield c


def mock_feeds(alex=200, family=200):
    respx.get(ALEX_URL).respond(alex, content=ALEX_ICS if alex == 200 else b"nope")
    respx.get(FAMILY_URL).respond(family, content=FAMILY_ICS if family == 200 else b"nope")


async def fetch(ccfg, http):
    return await CalendarProvider(ccfg, http).refresh(FIXED_NOW)


def by_title(events, title):
    return [e for e in events if e["title"] == title]


@respx.mock
async def test_matches_contract_and_sorted(ccfg, http, hub):
    mock_feeds()
    events = await fetch(ccfg, http)
    state = hub.empty_state()
    state["events"] = events
    assert_state_shape(state)
    starts = [datetime.fromisoformat(e["start"]) for e in events]
    assert starts == sorted(starts)
    assert {e["calendarId"] for e in events} == {"alex", "family"}


@respx.mock
async def test_rrule_with_exdate_and_moved_instance(ccfg, http):
    mock_feeds()
    sync = by_title(await fetch(ccfg, http), "Team sync")
    # Mon/Thu series: 22 Oct, 26 Oct (moved 10:00 -> 11:00), 29 Oct (EXDATE), 2 Nov.
    assert [(e["start"], e["end"]) for e in sync] == [
        ("2026-10-22T10:00:00+01:00", "2026-10-22T10:30:00+01:00"),
        ("2026-10-26T11:00:00+00:00", "2026-10-26T11:30:00+00:00"),
        ("2026-11-02T10:00:00+00:00", "2026-11-02T10:30:00+00:00"),
    ]
    assert all(e["allDay"] is False for e in sync)
    assert len({e["id"] for e in sync}) == 3
    moved = sync[1]
    assert moved["id"].startswith("alex:sync-series@test:")
    assert "2026-10-26T10:00:00" in moved["id"]  # keyed by RECURRENCE-ID, not new start


@respx.mock
async def test_event_after_clock_change_has_gmt_offset(ccfg, http):
    mock_feeds()
    [swim] = by_title(await fetch(ccfg, http), "Swimming")
    assert swim["start"] == "2026-10-26T14:00:00+00:00"
    assert swim["end"] == "2026-10-26T15:00:00+00:00"


@respx.mock
async def test_utc_event_converted_to_london(ccfg, http):
    mock_feeds()
    events = await fetch(ccfg, http)
    [call] = by_title(events, "Video call")
    assert call["start"] == "2026-10-24T10:00:00+01:00"
    [lunch] = by_title(events, "Lunch")
    assert lunch["start"] == "2026-10-28T12:00:00+00:00"


@respx.mock
async def test_x_wr_timezone_utc_does_not_shift_floating(ccfg, http):
    mock_feeds()
    events = await fetch(ccfg, http)
    [pickup] = by_title(events, "School pickup")
    assert pickup["start"] == "2026-10-23T17:30:00+01:00"
    assert pickup["end"] == "2026-10-23T18:30:00+01:00"
    assert pickup["calendarId"] == "family"
    # Floating recurring event keeps its wall time across the clock change.
    club = by_title(events, "Swim club")
    assert [e["start"] for e in club] == [
        "2026-10-24T18:00:00+01:00", "2026-10-31T18:00:00+00:00",
    ]


@respx.mock
async def test_all_day_single_day(ccfg, http):
    mock_feeds()
    [inset] = by_title(await fetch(ccfg, http), "Inset day")
    assert inset["allDay"] is True
    assert inset["start"] == "2026-10-23T00:00:00+01:00"
    assert inset["end"] == "2026-10-24T00:00:00+01:00"


@respx.mock
async def test_all_day_multi_day_exclusive_end_across_dst(ccfg, http):
    mock_feeds()
    [trip] = by_title(await fetch(ccfg, http), "Weekend away")
    assert trip["allDay"] is True
    assert trip["start"] == "2026-10-24T00:00:00+01:00"
    assert trip["end"] == "2026-10-27T00:00:00+00:00"


@respx.mock
async def test_all_day_missing_dtend_is_one_day(ccfg, http):
    mock_feeds()
    [bday] = by_title(await fetch(ccfg, http), "Birthday")
    assert bday["start"] == "2026-10-30T00:00:00+00:00"
    assert bday["end"] == "2026-10-31T00:00:00+00:00"


@respx.mock
async def test_window_bounds(ccfg, http):
    mock_feeds()
    events = await fetch(ccfg, http)
    titles = {e["title"] for e in events}
    assert "Already happened" not in titles
    assert "Too far ahead" not in titles
    [film] = by_title(events, "Late film")  # overlaps today's midnight
    assert film["start"] == "2026-10-21T22:00:00+01:00"
    [visit] = by_title(events, "Grandparents visiting")  # all-day overlapping start
    assert visit["start"] == "2026-10-20T00:00:00+01:00"
    assert visit["end"] == "2026-10-23T00:00:00+01:00"


@respx.mock
async def test_cancelled_dropped_and_untitled(ccfg, http):
    mock_feeds()
    events = await fetch(ccfg, http)
    assert not by_title(events, "Called off")
    [untitled] = by_title(events, "(No title)")
    assert untitled["location"] is None
    assert untitled["travelMins"] is None


@respx.mock
async def test_travel_mins(ccfg, http):
    mock_feeds()
    events = await fetch(ccfg, http)
    [swim] = by_title(events, "Swimming")
    assert swim["location"] == "Leisure centre"
    assert swim["travelMins"] == 15
    sync = by_title(events, "Team sync")
    assert sync[0]["location"] == "https://meet.google.com/x"
    assert all(e["travelMins"] is None for e in sync)
    assert by_title(events, "Video call")[0]["travelMins"] is None  # "Zoom meeting"
    assert by_title(events, "Lunch")[0]["travelMins"] is None  # "Online"
    assert by_title(events, "Late film")[0]["travelMins"] is None  # no location


@respx.mock
async def test_travel_mins_uses_config(ccfg, http):
    mock_feeds()
    cfg = replace(ccfg, calendar=CalendarSettings(default_travel_mins=25))
    events = await CalendarProvider(cfg, http).refresh(FIXED_NOW)
    assert by_title(events, "Swimming")[0]["travelMins"] == 25


def test_is_online():
    for loc in ("https://x.example", "Google Meet: meet.google.com/abc", "ZOOM", "MS Teams",
                "online"):
        assert is_online(loc)
    assert not is_online("Leisure centre")


@respx.mock
async def test_ids_stable_across_refreshes(ccfg, http):
    mock_feeds()
    provider = CalendarProvider(ccfg, http)
    first = [e["id"] for e in await provider.refresh(FIXED_NOW)]
    second = [e["id"] for e in await provider.refresh(FIXED_NOW)]
    assert first == second
    assert len(set(first)) == len(first)
    assert all(i.startswith(("alex:", "family:")) for i in first)


@respx.mock
async def test_one_feed_404_still_returns_other(ccfg, http, caplog, app_logging):
    mock_feeds(family=404)
    with caplog.at_level(logging.DEBUG):
        events = await fetch(ccfg, http)
    assert events and {e["calendarId"] for e in events} == {"alex"}
    assert "secret-family" not in caplog.text  # never log feed URLs


@respx.mock
async def test_request_urls_not_logged_at_info(ccfg, http, caplog, app_logging):
    mock_feeds()
    with caplog.at_level(logging.INFO):
        await fetch(ccfg, http)
    assert "example.invalid" not in caplog.text


@respx.mock
async def test_expansion_crash_isolated_and_not_logged(ccfg, http, caplog, monkeypatch):
    real = CalendarProvider._events

    def boom(self, cal_id, ical, lo, hi):
        if cal_id == "family":
            raise AttributeError(f"broken while reading {FAMILY_URL}")
        return real(self, cal_id, ical, lo, hi)

    monkeypatch.setattr(CalendarProvider, "_events", boom)
    mock_feeds()
    with caplog.at_level(logging.WARNING, logger="homehub.calendar"):
        events = await fetch(ccfg, http)
    assert events and {e["calendarId"] for e in events} == {"alex"}
    assert "AttributeError" in caplog.text
    assert "secret-family" not in caplog.text


@respx.mock
async def test_failing_feed_keeps_last_good(ccfg, http):
    provider = CalendarProvider(ccfg, http)
    mock_feeds()
    before = await provider.refresh(FIXED_NOW)
    respx.get(FAMILY_URL).respond(500)
    after = await provider.refresh(FIXED_NOW)
    assert after == before


@respx.mock
async def test_all_feeds_failing_raises_without_url(ccfg, http):
    mock_feeds(alex=404, family=404)
    with pytest.raises(Exception) as exc:
        await fetch(ccfg, http)
    text = str(exc.value) + repr(exc.value.__cause__) + repr(exc.value.__context__)
    assert "secret-" not in text


@respx.mock
async def test_hub_keeps_events_when_all_fail(ccfg, http):
    hub = Hub(ccfg, now=lambda: FIXED_NOW)
    hub.register("events", CalendarProvider(ccfg, http), 300)
    mock_feeds()
    assert await hub.refresh_one("events")
    good = hub.get_state()["events"]
    respx.get(ALEX_URL).respond(500)
    respx.get(FAMILY_URL).respond(500)
    assert not await hub.refresh_one("events")
    assert hub.get_state()["events"] == good


@respx.mock
async def test_summary_prints_counts_only(ccfg, http):
    mock_feeds()
    events = await fetch(ccfg, http)
    text = summarise(events, FIXED_NOW)
    assert "2026-10-22" in text and "2026-11-04" in text and "2026-11-05" not in text
    for e in events:
        assert e["title"] not in text
        assert e["id"] not in text
    assert "Leisure" not in text and "meet.google" not in text
