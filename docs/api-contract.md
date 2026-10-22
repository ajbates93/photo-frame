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
