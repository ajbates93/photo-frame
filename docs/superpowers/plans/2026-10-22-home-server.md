# Home Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Python home server that serves the dashboard and implements `docs/api-contract.md` with real data. The data comes from Google Calendar, Open-Meteo weather, a Google Drive photo folder, Google Keep, a local task store, Tapo plugs, the Nest speaker and Claude Code hooks, and the server also runs the screen on/off schedule. It is developed and run on the Mac first, then deployed to the Raspberry Pi 3A+.

**Architecture:** One FastAPI app run by uvicorn. Each data source is a **provider** with `async refresh() -> section`. A refresh loop runs each provider on its own interval, and the result is held in an in-memory `Hub`. `GET /api/state` assembles the cached sections, so it never blocks on a slow source. A provider that fails keeps its last good section and logs the error. A provider that has never succeeded yields the contract's empty or null value. Actions write through to their source, refresh that one section, and return the full State. Secrets and personal settings live in a git-ignored `server/config.toml`. The built dashboard (`dashboard/dist`) is served at `/`.

**Tech Stack:** Python ≥ 3.11, uv, FastAPI and uvicorn, httpx, `icalendar` with `recurring-ical-events`, `google-api-python-client` with `google-auth` (service account), Pillow, `gkeepapi` with `gpsoauth`, `python-kasa`, `pychromecast`, the `mcp` Python SDK (streamable HTTP), the standard-library sqlite3, pytest with pytest-asyncio, respx (to mock httpx) and ruff.

**Spec:** `docs/superpowers/specs/2026-10-22-photo-frame-dashboard-design.md`. **Contract:** `docs/api-contract.md` is authoritative for every response shape and every endpoint.

**Scope:** This is plan 2 of 4. Plan 3 covers the frame unlock and the kiosk, including the backlight. Plan 4 covers the Mac helpers: the activity LaunchAgent, the Claude Code hooks config and registering the MCP tool in Claude Code. This plan provides the **server endpoints** those helpers call.

## Global Constraints

- The JSON responses match `docs/api-contract.md` exactly: field names, types, nullability and the field semantics (event window, all-day exclusive end at local midnight, date-only task dues at local midnight, hourly weather from the current hour). Times are ISO 8601 with a `Europe/London` offset.
- All time handling uses `zoneinfo.ZoneInfo("Europe/London")`. iCal events use their own `TZID`. Floating times, and feeds whose `X-WR-TIMEZONE` is `UTC` (the Family feed is), are interpreted as Europe/London wall time, not UTC.
- Secrets live only in `server/config.toml` and `server/secrets/`. Both are git-ignored and created with mode `0600`. The repository is public: no calendar links, tokens, email addresses, home location or MAC addresses go into committed files, fixtures or test data. Fixtures use generic names.
- Endpoints the dashboard uses are open on the home network, because the frame holds no secrets. Write endpoints used by Mac helpers (`/api/claude/hook`, `/api/presence`, `/mcp`) require `Authorization: Bearer <shared_secret>` from config, and return 401 otherwise.
- Errors return `{"error": str}` with 400 (bad body or id), 404 (unknown id), 401, or 503 (source unavailable on write). Validation matches the dashboard mock in `dashboard/dev/mock-api.js`.
- A failing provider never breaks `/api/state`. Its section keeps the last good value (with `shopping.stale = true` for Keep), or the contract's empty/null value if it has never succeeded.
- The Pi 3A+ has 512 MB RAM. Steady-state server RSS must stay under 150 MB, so there are no heavy dependencies (no pandas, no headless browser), and image work happens one photo at a time.
- Reverse geocoding uses OpenStreetMap Nominatim at no more than 1 request/second, with a descriptive `User-Agent`, and results are cached on disk by rounded coordinates (3 decimal places), so each place is looked up once.
- Default refresh intervals: calendar 5 min, weather 30 min, photos 6 h, Keep 60 s, plugs 15 s, speaker 10 s, screen 15 s. All come from config.

## Review Focus

1. **Recurring and edited events.** A weekly event with one moved instance (RECURRENCE-ID) and one cancelled instance (EXDATE) must appear exactly once per remaining occurrence, at the right time, including across the 25 Oct 2026 clock change. Tested in Task 3.
2. **The Family feed declares UTC.** A floating or all-day event in it must not shift by an hour in BST. Tested in Task 3.
3. **Keep sync failure or conflicting edits.** When Keep is unreachable, the last list is kept with `stale: true`. A tick made on the frame while sync is down returns 503 and does not pretend to succeed. Nothing is ever deleted from Keep because of a sync error. Tested in Task 6.
4. **A device is offline.** An unreachable plug shows `reachable: false`, and toggling it returns 503 within 5 s, not after a long hang. A missing speaker makes `speaker` null. Neither slows down `/api/state`. Tested in Tasks 8 and 9.
5. **The screen schedule at the boundaries and on clock-change days.** At 22:00 the screen dims, at 23:00 it goes off and at 07:00 it comes on. With no Mac activity for 30 min in the day it goes off, and a wake keeps it on for 10 min. All of this holds on 25 Oct and 29 Mar. Tested in Task 5.

---

## File Structure

```
server/
  pyproject.toml, uv.lock, README.md
  config.example.toml          # committed template, no secrets
  config.toml                  # git-ignored (0600)
  secrets/                     # git-ignored (0600): drive-sa.json, keep-token, state.db, caches
  homehub/
    app.py                     # FastAPI app: routes, static dashboard, auth dependency
    config.py                  # load + validate config.toml → Config dataclasses
    hub.py                     # Hub: cached sections, refresh loop, State assembly
    timeutil.py                # LONDON tz, iso(), local_midnight(), window()
    providers/
      calendar.py  weather.py  photos.py  geocode.py  keep.py
      tasks.py     plugs.py    speaker.py claude.py   screen.py
    mcp_tasks.py               # MCP server (streamable HTTP) mounted at /mcp
  scripts/
    keep_token.py              # one-off: obtain a Keep master token
    deploy-pi.sh               # rsync + uv sync + systemd on the Pi
    homehub.service            # systemd unit
  tests/
    fixtures/*.ics, *.json     # generic, hand-written
    test_*.py
```

---

### Task 1: Scaffold, config and the State shell

**Files:**
- Create: `server/pyproject.toml`, `server/config.example.toml`, `server/homehub/{__init__,app,config,hub,timeutil}.py`, `server/tests/{conftest,test_app,test_config,test_timeutil}.py`, `server/README.md`
- Modify: `.gitignore` (add `server/config.toml`, `server/secrets/`, `server/.venv/`)
- Modify: `dashboard/vite.config.js`. When `VITE_API=server`, proxy `/api` to `http://localhost:8000` instead of using the mock plugin. Add the npm script `dev:server`.

**Interfaces:**
- Produces: `load_config(path) -> Config`. `Config` contains:
  - `people` and `calendars`, each a list of `{id, name|label, color, ics_url?}`;
  - `location {name, lat, lon}`;
  - `intervals`, `shared_secret`, `screen {dim_at:"22:00", off_at:"23:00", on_at:"07:00", idle_minutes:30, wake_minutes:10}`;
  - `keep {list_title, email}`, `drive {folder_id, service_account_file}`;
  - `plugs [{host, name?, room, confirm=false, hidden=false}]`, `tapo {username, password}`, `speaker {name}`.

  Missing optional sections disable their provider (its section becomes empty or null). A missing `shared_secret` is a startup error.
- Produces: `timeutil.LONDON`, `iso(dt) -> str` (offset form, seconds precision), `local_midnight(d: date) -> datetime`, `event_window(now) -> (start, end)` (today 00:00 to +14 days).
- Produces: `Hub` with `get_state() -> dict`, `set_section(name, value)` and `async run(providers)`. `Hub.empty_state()` returns a contract-valid State with every section empty or null and `screen {mode:'on'}`.
- Produces routes: `GET /api/state`, `GET /api/health`, and static `dashboard/dist` at `/` (index fallback), with a `require_secret` dependency for helper routes.
- Produces `server/tests/contract.py` with `assert_state_shape(state)`. It checks every key and type in the contract and is used by every later task's tests.

- [ ] **Step 1: Write failing tests:**
  - `test_empty_state_matches_contract`: `assert_state_shape(Hub(cfg).empty_state())`.
  - `test_get_state_200`: the TestClient's `/api/state` returns 200, and its body passes `assert_state_shape`.
  - `test_missing_secret_fails`: `load_config` raises on a config without `shared_secret`.
  - `test_iso_offset`: `iso(datetime(2026,10,22,8,42,tzinfo=LONDON)) == "2026-10-22T08:42:00+01:00"` and `iso(datetime(2026,10,26,9,0,tzinfo=LONDON)) == "2026-10-26T09:00:00+00:00"`.
  - `test_window`: `event_window` at 22 Oct 08:42 runs from `2026-10-22T00:00+01:00` to `2026-11-05T00:00+00:00`.
  - `test_index_served`: `/` returns the dashboard's `index.html` when `dist` exists. Skip if it isn't built.
- [ ] **Step 2: Run** `cd server && uv run pytest -q`. Expected: FAIL (modules missing).
- [ ] **Step 3: Implement.** Run uvicorn with `uv run homehub` (a console script) on `0.0.0.0:8000`. Configure logging to stdout.
- [ ] **Step 4: Run** `uv run pytest -q && uv run ruff check`. Expected: PASS. Also run `uv run homehub &` and check that `curl localhost:8000/api/state` returns JSON. Run `cd dashboard && npm run dev:server` and check the page loads with empty sections and no errors.
- [ ] **Step 5: Commit:** `feat(server): scaffold FastAPI hub, config, contract shape tests`

### Task 2: Weather (Open-Meteo)

**Files:** `server/homehub/providers/weather.py`, `server/tests/test_weather.py`, `server/tests/fixtures/open-meteo.json` (a recorded response for a generic lat/lon)

**Interfaces:**
- Consumes: `Config.location`, `timeutil`.
- Produces: `WeatherProvider(cfg, http).refresh(now) -> dict`, matching the contract's `weather`. It calls `https://api.open-meteo.com/v1/forecast` with `current=temperature_2m,weather_code,is_day`, `hourly=temperature_2m,weather_code,precipitation_probability`, `daily=temperature_2m_max,temperature_2m_min,sunrise,sunset`, `timezone=Europe/London` and `forecast_days=2`.
  - `wmo_to_cond(code, is_day) -> Cond`: 0 maps to sun (night when not day); 1–2 to partly; 3 to cloud; 45/48 to fog; 51–67 and 80–82 to rain; 71–77 and 85–86 to snow; 95–99 to storm.
  - `summary(hourly, now) -> str`: "Rain from 4pm." when rain probability is at least 50% at a later hour today, otherwise "Dry all day." A coat hint is appended when rain falls between 07:00 and 18:00.

- [ ] **Step 1: Write failing tests** with respx serving the fixture. Check that:
  - the result passes the shape test;
  - `hourly[0].time` is the current hour, and there are 6 or more entries;
  - temperatures are rounded integers;
  - `sunrise` and `sunset` are ISO with an offset;
  - the code→Cond mapping is right for 0 (day and night), 2, 3, 45, 61, 73 and 95;
  - `summary` gives "Rain from 4pm." when 16:00 has 70%.
  - An HTTP 500 raises, and the Hub keeps the previous section (test via `Hub.refresh_one`).
- [ ] **Step 2: Run** `uv run pytest tests/test_weather.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat(server): Open-Meteo weather provider`

### Task 3: Calendar (iCal feeds)

**Files:** `server/homehub/providers/calendar.py`, `server/tests/test_calendar.py`, `server/tests/fixtures/{alex,family-utc}.ics` (hand-written, generic titles)

**Interfaces:**
- Consumes: `Config.calendars[*].ics_url`, `timeutil.event_window`.
- Produces: `CalendarProvider(cfg, http).refresh(now) -> list[Event]` matching the contract `events`. Behaviour:
  - Feeds are fetched concurrently and parsed with `icalendar`. Occurrences in the window are expanded with `recurring_ical_events.of(cal).between(start, end)`.
  - `id = f"{calendarId}:{uid}:{recurrence-id or start}"`, stable across refreshes.
  - `title` is SUMMARY, or "(No title)". `location` is LOCATION or null.
  - `allDay` is true for DATE-valued DTSTART. Its start and end become `local_midnight(...)`, keeping DTEND exclusive. A missing DTEND means one day.
  - Timed events are converted to LONDON. Floating times (no TZID) are interpreted as LONDON wall time, whatever `X-WR-TIMEZONE` says.
  - `travelMins`: if the location is non-empty and doesn't look online (it doesn't contain `http`, `meet.google`, `zoom`, `teams` or `online`, case-insensitive), use `cfg.calendar.default_travel_mins` (default 15). Otherwise null.
  - Cancelled events (`STATUS:CANCELLED`) are dropped.
  - The result is sorted by start.
  - If one feed fails, events from the other still return, and the failing calendar keeps its last good events.

- [ ] **Step 1: Write failing tests** against the fixtures, with a clock fixed at 2026-10-22 08:42 London:
  - A weekly RRULE meeting has one EXDATE (gone) and one RECURRENCE-ID moved by an hour (it appears at the new time, once).
  - An event on 26 Oct after the clock change reports `+00:00` with the correct wall time.
  - In `family-utc.ics` (`X-WR-TIMEZONE:UTC`), a floating 17:30 event appears at `17:30+01:00`. A DATE all-day event on 23 Oct has start `2026-10-23T00:00:00+01:00` and end `2026-10-24T00:00:00+01:00`.
  - A 3-day all-day event has an exclusive end.
  - An event fully outside the window is excluded, and one overlapping the window start is included.
  - travelMins is 15 for "Leisure centre" and null for "https://meet.google.com/x".
  - Ids are stable across two refreshes.
  - One feed returning 404 still yields the other calendar's events.
- [ ] **Step 2: Run** `uv run pytest tests/test_calendar.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS. Then a manual smoke test against Alex's real feeds, with the links in `config.toml`: `uv run python -m homehub.providers.calendar --print-summary`. It prints counts per day only, never titles, into the shared log.
- [ ] **Step 5: Commit:** `feat(server): iCal calendar provider with recurrence and DST handling`

### Task 4: Task store (SQLite) and task actions

**Files:** `server/homehub/providers/tasks.py`, routes in `app.py`, `server/tests/test_tasks.py`

**Interfaces:**
- Produces a `TaskStore(path)` over `secrets/state.db`, with a `tasks(id TEXT PK, title, assignee, due TEXT NULL, done INT, created_at)` table:
  - `list() -> list[Task]` (sorted: not done first, then due ascending with nulls last, then created);
  - `add(title, assignee, due) -> Task`, with `id = uuid4().hex[:12]`;
  - `set_done(id, done)`;
  - `delete(id)`;
  - `prune(now)`, which deletes tasks that have been done for more than 7 days.
- Produces routes `POST /api/tasks`, `PATCH /api/tasks/{id}` and `DELETE /api/tasks/{id}`. Validation is the same as the mock: title is a non-empty string up to 200 characters; assignee is one of alex, vicky or any; due is null or a parseable ISO string (normalised to a LONDON offset); `done` is a bool. Unknown ids return 404. Every route returns the full State.

- [ ] **Step 1: Write failing tests:**
  - a CRUD round trip through the API, with each response passing the shape test;
  - each 400 case: empty title, a bad assignee, `due: "tomorrow"`, `done: "yes"`;
  - 404 for an unknown id;
  - a date-only due (`2026-10-23T00:00:00+01:00`) round-trips unchanged;
  - `prune` removes tasks done for 8 days and keeps those done for 6.
- [ ] **Step 2: Run** `uv run pytest tests/test_tasks.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat(server): SQLite task store and task endpoints`

### Task 5: Screen schedule and presence

**Files:** `server/homehub/providers/screen.py`, routes in `app.py`, `server/tests/test_screen.py`

**Interfaces:**
- Produces a pure function `screen_mode(now, last_activity: datetime|None, wake_until: datetime|None, cfg) -> 'on'|'dim'|'off'`. Rules, in order:
  1. If `wake_until` is in the future, the mode is `on`.
  2. Between `off_at` and `on_at` (23:00 to 07:00, wrapping midnight), it is `off`.
  3. Between `dim_at` and `off_at`, it is `dim`, unless there has been Mac activity in the last `idle_minutes`, in which case it is `on`.
  4. Otherwise, it is `on` if `last_activity` is within `idle_minutes`, and `off` if not. When there is no activity at all, it is `off`.
- Produces routes:
  - `POST /api/presence {active: bool, at?: ISO}` (secret required). It sets `last_activity`; `active:false` (Mac sleeping) clears it.
  - `POST /api/screen/wake` (open, from the frame). It sets `wake_until = now + wake_minutes` and returns the State.
- The Hub recomputes `screen` every 15 s and on each of these calls.

- [ ] **Step 1: Write failing tests**, table-driven over `screen_mode`:
  - At 12:00 with activity 5 min ago, the mode is on; with activity 31 min ago, it is off.
  - At 22:30 with no activity it is dim; with activity it is on.
  - At 23:30 it is off even with activity.
  - At 06:59 it is off; at 07:00 with recent activity, on.
  - A wake at 23:30 gives on until 23:40, then off.
  - On the clock-change days (25 Oct 2026 and 29 Mar 2026), the 23:00 and 07:00 boundaries happen at local wall time.
  - The presence route returns 401 without the bearer token. The wake route returns State with `screen.mode == "on"`.
- [ ] **Step 2: Run** `uv run pytest tests/test_screen.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat(server): screen schedule, Mac presence and wake`

### Task 6: Google Keep shopping list (two-way)

**Files:** `server/homehub/providers/keep.py`, `server/scripts/keep_token.py`, routes, `server/tests/test_keep.py`

**Interfaces:**
- Produces `KeepProvider(cfg)`, which logs in with `gkeepapi` using the frame account's email and the master token from `secrets/keep-token`. It persists `keep.dump()` state to `secrets/keep-state.json` for fast resume.
  - `refresh()` calls `keep.sync()`, finds the list whose title equals `cfg.keep.list_title` (case-insensitive), and maps it to `{items: [{id: item.id, text: item.text, checked: item.checked}], syncedAt, stale:false}`. Unchecked items come first, in Keep's order.
  - `add(text)` adds the item to the list, syncs, and returns a fresh section.
  - `set_checked(id, checked)` does the same for one item.
  - The provider never deletes items.
- On sync failure, `refresh` raises. The Hub then keeps the old items and sets `stale: true`, and `syncedAt` stays at the last success. Writes made while Keep is unreachable return 503 `{error:"Keep is unreachable"}`.
- Produces `scripts/keep_token.py`. It prompts for the frame account's email and an `oauth_token` cookie (following gkeepapi's documented master-token flow), exchanges them with `gpsoauth.exchange_token`, and writes `secrets/keep-token` with mode 0600. It never prints the token.
- Routes: `POST /api/shopping/items {text}` (non-empty, at most 200 characters) and `PATCH /api/shopping/items/{id} {checked: bool}`, with 404 for an unknown id.

- [ ] **Step 1: Write failing tests** with a fake Keep object (no network). Check:
  - The mapping and order are right.
  - Adding and checking call the right methods, then sync.
  - When sync raises, the section has `stale: true` with the old items, and a write returns 503 without calling `add`.
  - There is no code path that calls `delete` or `trash`: a test greps `keep.py` for both.
  - An unknown id returns 404, and the 400 cases match the mock.
  - A missing list title gives an empty items list with `stale:false`, plus a logged warning.
- [ ] **Step 2: Run** `uv run pytest tests/test_keep.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat(server): two-way Google Keep shopping list`

### Task 7: Photos from Google Drive (service account) with captions

**Files:** `server/homehub/providers/{photos,geocode}.py`, a route, `server/tests/{test_photos,test_geocode}.py`

**Interfaces:**
- Produces `PhotosProvider(cfg)`, using `google-api-python-client` with service-account credentials (`drive.readonly` scope).
  - `refresh()` lists images recursively under `folder_id` (`mimeType contains 'image/' and trashed=false`; it walks sub-folders, paging with `pageToken`). It requests the fields `id,name,mimeType,md5Checksum,imageMediaMetadata(time,location,width,height,rotation)`.
  - For each new `md5Checksum`, it downloads the file, applies the EXIF orientation, resizes to fit within 1280×800, and saves JPEG quality 82 to `secrets/photos/<md5>.jpg`. Only one image is in memory at a time. Cached files whose photos have been removed are deleted.
  - Returns `photos: [{id: md5, url: "/api/photos/<md5>", takenAt, place, width, height}]`, newest `takenAt` first, with undated photos last.
  - `takenAt` comes from `imageMediaMetadata.time` (`"YYYY:MM:DD HH:MM:SS"`, treated as LONDON local), or null.
  - `place` is `geocode(lat, lon)` or null.
- Produces `Geocoder(cache_path, http)`. `place(lat, lon) -> str|None` calls Nominatim `reverse?format=jsonv2&zoom=14`, picking the first of `village`, `town`, `suburb`, `city` or `county`. It throttles to 1 request/s, sends a `User-Agent` of `homehub-photo-frame (github.com/<owner>/photo-frame)`, and caches by `round(lat,3),round(lon,3)` in `secrets/geocode.json`, including misses.
- Route: `GET /api/photos/{id}` serves the cached file with `Cache-Control: public, max-age=31536000, immutable`. A non-hex id returns 400 and an unknown id 404.

- [ ] **Step 1: Write failing tests** with a fake Drive service and respx for Nominatim. Check:
  - Recursive listing across two pages and a sub-folder.
  - A 4000×3000 image becomes 1067×800, and a portrait image with EXIF orientation 6 is rotated.
  - The cache is reused when the md5 is unchanged, and an orphaned file is removed.
  - `takenAt` parses with the BST offset.
  - The geocoder falls back from village to town, caches, makes a second call for the same rounded coordinates with no HTTP request, and spaces two different lookups at least 1 s apart (using a fake clock).
  - The route returns the right headers, 400 for `../x` and 404 for an unknown id.
- [ ] **Step 2: Run** `uv run pytest tests/test_photos.py tests/test_geocode.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat(server): Drive photo folder with resize cache and place captions`

### Task 8: Tapo plugs

**Files:** `server/homehub/providers/plugs.py`, a route, `server/tests/test_plugs.py`

**Interfaces:**
- Produces `PlugsProvider(cfg)` using python-kasa (`Discover.discover_single(host, username, password)` per configured host, with the connection kept).
  - `refresh()` returns `plugs: [{id: <stable id from config host or device id>, name: cfg.name or device alias, room, on, reachable, confirm, hidden}]`.
  - Each device update has a 4 s timeout. On a timeout, that plug is `reachable:false` with its last `on` value.
  - `set(id, on)` toggles the plug, with a 5 s timeout. If the plug is unreachable, it returns 503 `{error:"<name> is offline"}`.
- Route: `POST /api/plugs/{id} {on: bool}`, with 400 for a non-bool and 404 for an unknown id.

- [ ] **Step 1: Write failing tests** with fake kasa devices. Check:
  - The mapping, with config name and room overriding the alias.
  - A device that hangs is marked `reachable:false` within 4.5 s, while the other plugs still update.
  - Toggling an offline plug returns 503 within 5.5 s.
  - The 400 and 404 cases.
  - `hidden` and `confirm` are passed through.
- [ ] **Step 2: Run** `uv run pytest tests/test_plugs.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS. Then a manual smoke test on the Mac against the real P100s: list the plugs, toggle the office lamp on and off.
- [ ] **Step 5: Commit:** `feat(server): Tapo plug provider with timeouts`

### Task 9: Nest speaker (Cast)

**Files:** `server/homehub/providers/speaker.py`, a route, `server/tests/test_speaker.py`

**Interfaces:**
- Produces `SpeakerProvider(cfg)`, which uses `pychromecast.get_listed_chromecasts(friendly_names=[cfg.speaker.name])` in a worker thread, started once. Discovery is retried every 5 minutes while the speaker isn't found.
  - `refresh()` returns `{name, reachable, playing: player_state == 'PLAYING', title, artist, volume: round(volume_level*100)}`, or null when the speaker isn't configured or has never been found.
  - `play()` and `pause()` act through `media_controller`. `volume(v)` clamps to 0–100 and calls `set_volume(v/100)`.
  - Calls run in a thread with a 5 s timeout. An unreachable speaker returns 503.
- Route: `POST /api/speaker {action, volume?}`, validated exactly as the mock.

- [ ] **Step 1: Write failing tests** with a fake cast. Check:
  - The status mapping, with `volume_level` 0.37 giving 37.
  - Play, pause and volume calls go through; `volume` 120 clamps to 100.
  - An unknown action and a missing volume each return 400.
  - A never-found speaker gives `speaker: null` in State, and actions return 503.
- [ ] **Step 2: Run** `uv run pytest tests/test_speaker.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS. Then a manual smoke test against the kitchen Nest Mini.
- [ ] **Step 5: Commit:** `feat(server): Nest speaker via Cast`

### Task 10: Claude sessions (hooks) and usage

**Files:** `server/homehub/providers/claude.py`, a route, `server/tests/test_claude.py`

**Interfaces:**
- Produces `POST /api/claude/hook` (secret required), which accepts a Claude Code hook payload as JSON. It reads `hook_event_name`, `session_id` and `cwd`, and optionally `message`. Project = basename of `cwd`. State transitions:
  - `UserPromptSubmit`, `PreToolUse` and `PostToolUse` → `working`;
  - `Notification` (when the message asks for permission or input) → `waiting`;
  - `Stop` → `done`;
  - `SessionEnd` → removed.
  - `since` updates only when the state changes.

  Sessions that have been `done` for more than 30 min, or silent for more than 6 h, are pruned.
- Produces `claude.sessions` in State. `claude.usage` comes from an optional `UsageSource`. The default is `NullUsage` (usage null). The usage route is best-effort, and the spec accepts that it may break. `POST /api/claude/usage` (secret required) accepts `{plan, session:{pct,resetsAt}, weekly:{pct,resetsAt}}` pushed from the Mac (plan 4 decides how the Mac obtains it). Values are validated (pct between 0 and 100, ISO resetsAt), and usage older than 30 min reverts to null.

- [ ] **Step 1: Write failing tests:**
  - the sequence UserPromptSubmit → Notification(permission) → PostToolUse → Stop gives working → waiting → working → done, with the right `since` changes;
  - SessionEnd removes the session;
  - pruning after 31 min done and after 6 h silent;
  - 401 without the secret;
  - a bad usage payload returns 400;
  - stale usage returns null after 30 min.
- [ ] **Step 2: Run** `uv run pytest tests/test_claude.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat(server): Claude Code session status via hooks and pushed usage`

### Task 11: MCP task tool

**Files:** `server/homehub/mcp_tasks.py`, mounted in `app.py`; `server/tests/test_mcp_tasks.py`

**Interfaces:**
- Consumes: `TaskStore` (Task 4).
- Produces an MCP server, built with the official `mcp` SDK's `FastMCP` and mounted at `/mcp` as streamable HTTP behind `require_secret`. Its tools:
  - `add_task(title: str, assignee: Literal['alex','vicky','any']='any', due: str|None=None)`. `due` is ISO; a date with no time means date-only, stored at local midnight.
  - `list_tasks(include_done: bool=False)`;
  - `complete_task(id: str)`;
  - `delete_task(id: str)`.

  The tool descriptions tell Claude that the time zone is Europe/London, that "after work" means 18:00 local, and that a due date with no time should be date-only. Each tool returns a short human-readable confirmation plus the task as JSON.

- [ ] **Step 1: Write failing tests** using the SDK's in-process client. Check:
  - `add_task` with a date-only due stores local midnight.
  - The listed tasks exclude done ones by default.
  - `complete_task` and `delete_task` work by id, and an unknown id returns a tool error.
  - An HTTP call to `/mcp` without the bearer token returns 401.
- [ ] **Step 2: Run** `uv run pytest tests/test_mcp_tasks.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat(server): MCP tool for adding family tasks`

### Task 11a: Routine-aware weather hints

**Files:** modify `server/homehub/providers/weather.py`, `server/homehub/config.py`, `server/config.example.toml`; tests in `server/tests/test_weather.py`.

**Interfaces:**
- Config gains `[[routines]]` entries: `{label: str, days: list["mon".."sun"], start: "HH:MM", end: "HH:MM"}`. The labels are personal, so they live only in the git-ignored `config.toml`. The example file uses generic labels ("School run", "Evening walk").
- Alex's real routines live only in his git-ignored config.toml.
- Open-Meteo request adds hourly `wind_gusts_10m` and `apparent_temperature` (still `timeformat=unixtime`).
- `summary(hourly, now, routines) -> str` produces at most two short sentences. The rules:
  1. The **next routine** is the first routine today whose `end` is after `now`.
  2. If there is one, look at the hourly entries overlapping `[start, end)`:
     - rain is any hour with `rainPct >= 50`;
     - wind is any gust of 40 km/h or more (≥ 60 counts as "very windy");
     - cold is apparent temperature of 3°C or less.
  3. Phrase the conditions found, in that priority order (rain, wind, cold), with the routine label and its start time. Examples:
     - "Rain likely for Swim class (10am) — take a coat."
     - "Very windy at Football (4pm)."
     - "Cold (2°) for Early run (6:30am)."

     Combine at most two conditions: "Rain and wind for …". With none, the hint is "Dry for the {label} ({time})."
  4. When there is no routine left today (weekends, or after the last one), use the general forecast for the rest of today: "Rain from 4pm.", "Showers this morning, clearing by 1pm.", "Dry rest of the day.", or, after 6pm, "Rain overnight." / "Dry tonight." Append "Windy this afternoon." when the gust rule fires.
- Day-of-week and times use Europe/London wall time. `label` strings are lower-cased mid-sentence only if they start with a capital and aren't proper nouns — keep it simple: use the label as written in config.

- [ ] **Step 1: Write failing tests** for the following. The clock is fixed and the routines are generic.
  - At Wed 09:00 with rain at 10:00, the hint mentions the swim class.
  - On a day without the swim class, the next routine is football.
  - On a day with no routine left, the general forecast is used.
  - At Sat, the general forecast is used.
  - Gusts of 65 give "Very windy".
  - Apparent temperature 2 gives "Cold (2°)".
  - Two conditions combine.
  - After the swim class ended, the next routine is football.
  - On the clock-change day (Sun 25 Oct) the general forecast is used.
- [ ] **Step 2: Run** `uv run pytest tests/test_weather.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full suite and ruff. Expected: PASS. Put Alex's routines into his local `config.toml` only (it is git-ignored).
- [ ] **Step 5: Commit:** `feat(server): routine-aware weather hints (rain, wind, cold)`

### Task 12: Wire it all up and run on the Mac with real data

**Files:** modify `app.py` and `hub.py` (provider registry and lifespan start/stop); create `server/README.md` (setup guide); create `server/tests/test_integration.py`.

**Interfaces:**
- Produces: on startup, the lifespan builds providers from config, skipping unconfigured ones, starts `Hub.run`, and cancels it cleanly on shutdown.
- Produces: `uv run homehub --check` loads the config, tries one refresh of each provider and prints a one-line OK, FAIL or SKIP per provider. It shows counts only, never titles, names or URLs.
- `server/README.md` gives Alex's one-time setup steps in plain prose:
  - copying `config.example.toml`;
  - creating the Google Cloud project, enabling the Drive API, creating a service account, downloading its JSON key to `secrets/drive-sa.json` and sharing the photo folder with the service account's email as Viewer;
  - running `scripts/keep_token.py` for the frame account;
  - enabling Tapo third-party compatibility and listing the plug IPs (with DHCP reservations recommended);
  - setting the speaker name;
  - generating `shared_secret` (`python -c "import secrets;print(secrets.token_urlsafe(32))"`).

- [ ] **Step 1: Write a failing integration test.** With fake providers that are slow, failing or good, `/api/state` responds in under 100 ms while one provider hangs, a failing provider's section keeps its last value, and the response passes the shape test.
- [ ] **Step 2: Run** `uv run pytest -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -q && uv run ruff check`. Expected: PASS. Then, **with Alex**:
  1. Fill in `config.toml`.
  2. Run `uv run homehub --check`. Every provider should be OK or a deliberate SKIP.
  3. Run `uv run homehub` and `cd dashboard && npm run dev:server`.
  4. Alex confirms on localhost: real calendar events, weather, photos with captions, the Keep list ticking both ways, a lamp toggling, and the speaker playing and pausing.
  5. Check RSS with `ps -o rss= -p <pid>` after 10 minutes: expected under 150 MB.
- [ ] **Step 5: Commit:** `feat(server): provider wiring, --check, setup guide`

### Task 13: Deploy to the Raspberry Pi (when it arrives)

**Files:** `server/scripts/deploy-pi.sh`, `server/scripts/homehub.service`, a deploy section in `server/README.md`

**Interfaces:**
- `deploy-pi.sh <host>` performs these steps:
  1. Builds the dashboard (`npm run build`).
  2. Rsyncs `server/` (excluding `.venv`, `secrets` and `config.toml`) and `dashboard/dist` to `~/homehub` on the Pi.
  3. Runs `uv sync --frozen` there.
  4. On the first run only, copies `config.toml` and `secrets/` across over SSH with mode 0600.
  5. Installs and enables `homehub.service` (User=pi, `Restart=always`, `MemoryMax=200M`) and restarts it.
- The Pi needs Raspberry Pi OS Lite **64-bit** (Bookworm or later) — pillow and pillow-heif publish no armv7 wheels, so the 32-bit image cannot install them — plus uv and a DHCP reservation on the router.

- [ ] **Step 1: Write a test.** It runs `bash -n deploy-pi.sh` and greps the service file for `Restart=always` and `MemoryMax`.
- [ ] **Step 2: Run** the test. Expected: FAIL until the files exist.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: With Alex, once the Pi is set up:** run the deploy and `curl http://<pi>:8000/api/health`. Check RSS on the Pi after 30 min.
- [ ] **Step 5: Commit:** `feat(server): Pi deployment script and systemd unit`
