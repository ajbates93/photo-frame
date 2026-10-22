# Dashboard API contract

This document is authoritative for the dashboard frontend and for the backend (plan 2). The frontend polls `GET /api/state` and sends actions to the endpoints below. Everything is served from the dashboard's own origin.

## State

```ts
type ISO = string // ISO 8601 with offset
State = {
  generatedAt: ISO, timezone: 'Europe/London',
  people: {id: string, name: string, color: string}[],          // e.g. alex, vicky
  calendars: {id: string, label: string, color: string}[],
  events: {id, calendarId, title, start: ISO, end: ISO, allDay: boolean,
           location: string|null, travelMins: number|null}[],
  weather: null | {location: string, temp: number, cond: Cond, label: string, hi: number, lo: number,
           summary: string, sunrise: ISO, sunset: ISO,
           hourly: {time: ISO, temp: number, cond: Cond, rainPct: number}[]},
  photos: {id, url: string, takenAt: ISO|null, place: string|null, width: number, height: number}[],
  shopping: {items: {id, text: string, checked: boolean}[], syncedAt: ISO|null, stale: boolean},
  tasks: {id, title: string, assignee: 'alex'|'vicky'|'any', due: ISO|null, done: boolean}[],
  plugs: {id, name: string, room: string, on: boolean, reachable: boolean, confirm: boolean, hidden: boolean}[],
  speaker: null | {name: string, reachable: boolean, playing: boolean, title: string|null,
           artist: string|null, volume: number /*0-100*/},
  claude: {sessions: {id, project: string, state: 'working'|'waiting'|'done', since: ISO}[],
           usage: null | {plan: string, session: {pct: number, resetsAt: ISO}, weekly: {pct: number, resetsAt: ISO}}},
  screen: {mode: 'on'|'dim'|'off'}
}
Cond = 'sun'|'partly'|'cloud'|'rain'|'snow'|'fog'|'storm'|'night'
```

### Field semantics

- **Time zone.** The frontend renders every time in the device's local time zone, which must be set to `Europe/London`. The `timezone` field is informational only; the frontend does not convert with it.
- **Event window.** `events` carries every event overlapping the window from the start of today (local midnight) to today + 14 days. The calendar view never pages before today and disables its › button once the next page would start beyond that window.
- **All-day events.** `allDay: true` events have `start` and `end` at local midnight, as ISO with offset (e.g. `2026-10-23T00:00:00+01:00`). `end` is exclusive, Google style: a one-day event on 23 October ends at `2026-10-24T00:00:00+01:00`.
- **Task due.** `due` is an ISO instant or `null`. A `due` at exactly local midnight means the task is due on that date with no time: the frontend shows `today`, `tomorrow` or the weekday without a time, and treats it as overdue only once that day has ended. Any other instant is a timed due, overdue once it has passed.
- **Hourly weather.** `weather.hourly` starts at the current hour and runs forward. The frontend also drops any entry before the current hour and shows at most six.

## Actions

Each action returns the full new `State`. Errors return `{error: string}` with a 4xx or 5xx status.

| Method and path | Body |
| --- | --- |
| `POST /api/shopping/items` | `{text}` |
| `PATCH /api/shopping/items/:id` | `{checked}` |
| `POST /api/tasks` | `{title, assignee, due}` |
| `PATCH /api/tasks/:id` | `{done}` |
| `DELETE /api/tasks/:id` | none |
| `POST /api/plugs/:id` | `{on}` |
| `POST /api/speaker` | `{action: 'play'\|'pause'\|'volume', volume?}` |
| `POST /api/screen/wake` | none |

## Helper endpoints (bearer secret)

These are not used by the dashboard. Each requires `Authorization: Bearer <shared_secret>` and returns `401 {error}` otherwise. Errors are `{error: string}`.

| Method and path | Body | Response |
| --- | --- | --- |
| `POST /api/presence` | `{active: boolean, at?: ISO with offset}` | `{ok: true, mode: 'on'\|'dim'\|'off'}` |
| `POST /api/claude/hook` | a Claude Code hook payload, verbatim JSON (`hook_event_name`, `session_id` required; `cwd`, `notification_type`, `tool_name` used; everything else ignored and never stored) | `{ok: true}` |
| `POST /api/claude/usage` | `{plan: string, session: {pct, resetsAt}, weekly: {pct, resetsAt}}`, `pct` a number 0-100, `resetsAt` ISO with offset | `{ok: true}` |

- `400` for a body that is not a JSON object, a missing or invalid field, or a `session_id` that is empty, longer than 200 characters or not valid UTF-8.
- `413` when a `claude` body exceeds 256 KB.
- Usage older than 30 minutes is reported as `claude.usage: null`.
- Hook states: `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SessionStart` give `working`; a `Notification` of type `permission_prompt` or `elicitation_dialog` (or, without a type, a message mentioning "permission"), or a `PreToolUse` for `AskUserQuestion`, gives `waiting`; `idle_prompt` changes nothing; `Stop` gives `done`; `SessionEnd` removes the session. Sessions `done` for over 30 min or silent for over 6 h are dropped.

## Photos

`GET /api/photos/:id` returns the image bytes for a photo listed in `State.photos` (its `url`). The response is `image/jpeg` (the dev mock may serve `image/svg+xml`), at most 1280 × 800, and cacheable: the server sends a long-lived `Cache-Control` header, since a photo's bytes never change for a given id.
