# Dashboard Front End (Mock API) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the frame's dashboard web page (home "command centre" plus seven full screens, day/night themes, dim/off overlay), running on the Mac against a mock API whose JSON shape is the contract the Pi server will implement later.

**Architecture:** A vanilla-JS ES-module app built with Vite, no UI framework (the frame has 1 GB RAM and WebView 106). A single polling store fetches one `State` snapshot from `GET /api/state` and re-renders. User actions POST to small endpoints that return the new `State`. In development a Vite plugin serves the mock API from in-memory fixtures generated relative to "now". Pure logic (calendar layout, captions, theme, formatting) lives in `src/lib/` and is unit-tested. Views render HTML strings into their section.

**Tech Stack:** Vite, Vitest + jsdom, `@fontsource/instrument-serif` and `@fontsource-variable/archivo` (self-hosted fonts), headless Chrome for screenshots.

**Spec:** `docs/superpowers/specs/2026-10-22-photo-frame-dashboard-design.md`. The approved visual is `docs/superpowers/specs/mockups/2026-10-22-home-command-centre.html` (the "Warm paper" and "Night" screens).

**Scope:** This is plan 1 of 4. Plan 2 covers the Pi server and its integrations, plan 3 the frame unlock and kiosk, and plan 4 the Mac helpers. Out of scope here: real data, backlight control, the Python server, and the kiosk app.

## Global Constraints

- The JS build target is `chrome106`, and `build.cssTarget` is `chrome61` (copied from Wes's `vite.config.js`). The frame's WebView rejects 4- and 8-digit hex colours.
- CSS must not use nesting, `color-mix()`, `oklch()`, `dvh`/`svh`/`lvh`, or 4- or 8-digit hex colours. Use `rgba()`.
- The viewport is fixed at 1280 × 800 (`<meta name="viewport" content="width=1280, initial-scale=1, user-scalable=no">`), and the body never scrolls.
- No control's whole tap area may sit inside the bottom 64 px of the screen. An invisible system overlay swallows taps there on the PF1007L.
- Don't rely on multi-touch gestures. The touch panel merges fingers closer than about 2.5 cm.
- The page makes no network requests except to its own origin. Fonts are self-hosted, and there are no CDNs or third-party images.
- No secrets in the front end, fixtures or repo. Fixtures use generic place names, never the household's real town or addresses.
- All times display in `Europe/London`. The time format is `8:42am` / `5:30pm` (lowercase, no space). Tests run with `TZ=Europe/London`.
- Every `State` field the spec marks optional (`weather`, `speaker`, `claude.usage`, a photo's `takenAt` and `place`) can be `null`. Views render a placeholder for a null field and never throw.
- Themes: `paper` by day and `night` between sunset and sunrise, with a 3 s cross-fade. Both themes use DM Serif Display for headings.
- At most two slideshow `<img>` elements are in the DOM at any time.

## Review Focus

1. **Overlapping events** (Alex's call and a family event at the same time) must sit side by side in the calendar, never on top of each other. Tested in Task 3.
2. **Events outside the 08:00–21:00 grid** (a 06:30 gym, a 22:00 film) must be clamped to the grid's edge with their real time in the label, not disappear. Tested in Task 3.
3. **The clock-change day** (Sunday 25 October 2026) and **midnight rollover**: hour rows and the Today/Tomorrow labels must be right without a page reload. Tested in Tasks 2 and 3.
4. **The Pi unreachable or a section null**: the last good data stays on screen with a "stale" marker; a null section shows a placeholder, and the screen never goes blank. Tested in Tasks 4 and 5.
5. **Long or plentiful content**: a 60-character event title, a 25-item shopping list or 15 tasks are truncated with ellipses or scroll inside their tile, and never push the layout. Tested in Tasks 6 and 8.

---

## File Structure

```
dashboard/
  package.json, vite.config.js, vitest.config.js, index.html
  scripts/check-compat.mjs      # fails the build on forbidden CSS
  scripts/screenshot.mjs        # headless Chrome 1280×800 screenshots per view/theme
  dev/fixtures.js               # makeFixtureState(now) -> State
  dev/mock-api.js               # Vite plugin: /api/* in memory
  src/main.js                   # boot: store, router, views, theme, screen overlay
  src/api.js                    # fetch wrappers
  src/store.js                  # polling store
  src/router.js                 # view switching + idle return to home
  src/lib/time.js               # formatting + day maths
  src/lib/calendar.js           # layoutDay, allDayOn, nextEvent
  src/lib/captions.js           # photoCaption
  src/lib/theme.js              # themeFor
  src/ui/icons.js               # SVG icon strings (port from Wes)
  src/ui/slideshow.js           # two-<img> cross-fade slideshow (port from Wes)
  src/views/{home,calendar,shopping,tasks,photos,control,claude}.js
  src/css/tokens.css, base.css, views/*.css
  test/*.test.js
docs/api-contract.md            # State + action endpoints (the Pi must match)
NOTICE.md                       # MIT attribution for code ported from wesbos/photo-frame-dashboard
```

Code ported from Wes's repo (MIT) comes from `wesbos/photo-frame-dashboard/dashboard/` at commit `main` as cloned on 22 October 2026. Port only `js/icons.js` and `js/slideshow.js`, and use `css/tokens.css` as a starting palette. Everything else is new, because Wes's views are bound to the global mock `window.DATA`.

---

### Task 1: Scaffold, build constraints and the API contract

**Files:**
- Create: `dashboard/package.json`, `dashboard/vite.config.js`, `dashboard/vitest.config.js`, `dashboard/index.html`, `dashboard/scripts/check-compat.mjs`, `dashboard/src/main.js` (stub), `docs/api-contract.md`, `NOTICE.md`
- Test: `dashboard/test/compat.test.js`

**Interfaces:**
- Produces: npm scripts `dev`, `build` (runs `vite build`, then `node scripts/check-compat.mjs dist`), `test` (`vitest run`), `screens` (Task 10). `check-compat.mjs` exports `findViolations(cssText: string): string[]`.
- Produces: `docs/api-contract.md`, which defines the following and is authoritative for every later task and for plan 2:

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

  Actions (each returns the full new `State`; errors return `{error: string}` with a 4xx or 5xx status):
  `POST /api/shopping/items {text}` · `PATCH /api/shopping/items/:id {checked}` · `POST /api/tasks {title, assignee, due}` · `PATCH /api/tasks/:id {done}` · `DELETE /api/tasks/:id` · `POST /api/plugs/:id {on}` · `POST /api/speaker {action: 'play'|'pause'|'volume', volume?}` · `POST /api/screen/wake`.

- [ ] **Step 1: Write the failing test.** In `test/compat.test.js`:

```js
import { findViolations } from '../scripts/check-compat.mjs';
test('flags forbidden CSS', () => {
  expect(findViolations('a{color:#ffffffbf}')).toHaveLength(1);
  expect(findViolations('a{color:#0000}')).toHaveLength(1);
  expect(findViolations('a{color:color-mix(in srgb,red,blue)}')).toHaveLength(1);
  expect(findViolations('a{height:100dvh}')).toHaveLength(1);
  expect(findViolations('a{&:hover{color:red}}')).toHaveLength(1);
  expect(findViolations('a{color:#fff;background:#f2eee6;height:100vh}')).toEqual([]);
});
```

- [ ] **Step 2: Run** `cd dashboard && npm i && npx vitest run test/compat.test.js`. Expected: FAIL (module not found).
- [ ] **Step 3: Implement `findViolations` and the CLI** in `scripts/check-compat.mjs`, using regexes for `#[0-9a-f]{4}\b|#[0-9a-f]{8}\b`, `color-mix\(`, `oklch\(`, `\d(d|s|l)vh\b` and a nested `&` selector. The CLI reads every `.css` in the given dir, prints violations and exits 1. Configure `vite.config.js` with `build.target: 'chrome106'`, `build.cssTarget: 'chrome61'`, `server.host: true` and the mock-API plugin slot, and `vitest.config.js` with `environment: 'jsdom'` and `env: { TZ: 'Europe/London' }`. `index.html` has the viewport meta from the constraints, a `<nav class="rail">` with seven buttons (`data-go` = home, calendar, tasks, shopping, photos, control, claude), seven `<section class="view" data-view="…">`, `#overlay` (dim/off) and `#toasts`. Write `docs/api-contract.md` from the Interfaces block above, and `NOTICE.md` with Wes's MIT licence text and the ported file list.
- [ ] **Step 4: Run** `npx vitest run && npm run build`. Expected: the tests pass, the build succeeds and the compat check prints `0 violations`.
- [ ] **Step 5: Commit:** `git add dashboard docs/api-contract.md NOTICE.md && git commit -m "feat(dashboard): scaffold with WebView 106 build checks and API contract"`

### Task 2: Time formatting and day maths

**Files:**
- Create: `dashboard/src/lib/time.js`
- Test: `dashboard/test/time.test.js`

**Interfaces:**
- Produces: `fmtTime(d: Date): string` ("8:42am", "12:00pm", "5:30pm"); `fmtHour(h: number): string` ("9am", "12pm"); `fmtRange(a: Date, b: Date): string` ("11:30am–12:30pm"); `fmtDay(d: Date): string` ("Thursday"); `fmtDate(d: Date): string` ("22 October"); `fmtCountdown(mins: number): string` ("38 min", "8h 48"); `dayStart(d: Date): Date`; `addDays(d: Date, n: number): Date`; `hoursSinceDayStart(d: Date, day: Date): number` (wall-clock hours, correct across a DST change).

- [ ] **Step 1: Write failing tests**, including:

```js
expect(fmtTime(new Date('2026-10-22T08:42:00+01:00'))).toBe('8:42am');
expect(fmtTime(new Date('2026-10-22T12:00:00+01:00'))).toBe('12:00pm');
expect(fmtRange(new Date('2026-10-22T11:30:00+01:00'), new Date('2026-10-22T12:30:00+01:00'))).toBe('11:30am–12:30pm');
expect(fmtCountdown(38)).toBe('38 min'); expect(fmtCountdown(528)).toBe('8h 48');
// clock change: Sun 25 Oct 2026, 02:00 BST -> 01:00 GMT
const day = new Date('2026-10-25T00:00:00+01:00');
expect(hoursSinceDayStart(new Date('2026-10-25T09:00:00Z'), day)).toBe(9); // 09:00 GMT is 9am local
expect(addDays(day, 1).getDate()).toBe(26); expect(addDays(day, 1).getHours()).toBe(0);
```

- [ ] **Step 2: Run** `npx vitest run test/time.test.js`. Expected: FAIL.
- [ ] **Step 3: Implement** the functions in `src/lib/time.js`. `hoursSinceDayStart` uses local `getHours()` and `getMinutes()` (wall clock), not millisecond differences.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit:** `git commit -am "feat(dashboard): time formatting and DST-safe day maths"` (add new files first).

### Task 3: Calendar logic

**Files:**
- Create: `dashboard/src/lib/calendar.js`
- Test: `dashboard/test/calendar.test.js`

**Interfaces:**
- Consumes: `State.events`, `State.calendars`, and the Task 2 time helpers.
- Produces:
  - `GRID = { startHour: 8, endHour: 21 }`
  - `layoutDay(events, day: Date, now: Date, grid = GRID): Block[]`, where `Block = { event, topPct, heightPct, col, cols, short, past, clampedStart, clampedEnd }`. It takes timed (non-all-day) events that intersect `day` only.
  - `allDayOn(events, day: Date): Event[]`, covering all-day and multi-day all-day events.
  - `nextEvent(events, now: Date): Event|null`: the first timed event with `start > now`, looking ahead up to 48 h.
  - `leaveBy(event): Date|null`: `start - travelMins`, or `null` when `travelMins` is null.

- [ ] **Step 1: Write failing tests**, one each for these:
  - `layoutDay` for a 09:00–09:30 event: `topPct ≈ 7.69`, `heightPct ≈ 3.85`, `short === true` (duration under 60 min).
  - Two events 17:30–18:15 and 17:45–19:00: both have `cols === 2`, with `col` values 0 and 1.
  - A 06:30–07:15 event: `topPct === 0`, `clampedStart === true`, and it's still returned.
  - A 22:00–23:00 event: it's returned, `clampedStart === true`, and its top sits at the grid's bottom edge minus a minimum block height of 3%.
  - A 23:30–00:30 event spanning midnight appears in both days' layouts.
  - `past === true` when `end <= now`.
  - On 25 Oct 2026 (the clock-change day), a 09:00 local event has `topPct ≈ 7.69`.
  - `allDayOn` returns a three-day all-day event on each of its three days and not on the fourth.
  - At 23:59, `nextEvent` returns tomorrow's 09:00 event. At 18:00 with nothing left today, it returns tomorrow's first event. With no events in 48 h, it returns `null`.
  - `leaveBy` returns 17:10 for start 17:30 and `travelMins` 20.
- [ ] **Step 2: Run** `npx vitest run test/calendar.test.js`. Expected: FAIL.
- [ ] **Step 3: Implement.** Overlap columns: sort by start, group transitively overlapping events into clusters, assign each the lowest free column, and set `cols` to the cluster's column count. Clamped events keep their real `start` and `end` for labels.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit:** `git commit -m "feat(dashboard): calendar layout with overlaps, clamping and DST"`.

### Task 4: Mock API, fixtures, API client and polling store

**Files:**
- Create: `dashboard/dev/fixtures.js`, `dashboard/dev/mock-api.js`, `dashboard/src/api.js`, `dashboard/src/store.js`
- Modify: `dashboard/vite.config.js` (register the plugin in `serve` mode only)
- Test: `dashboard/test/store.test.js`, `dashboard/test/mock-api.test.js`

**Interfaces:**
- Consumes: the contract in `docs/api-contract.md`.
- Produces:
  - `makeFixtureState(now: Date): State`. Its content mirrors the approved mockup, with generic places: Alex's calendar (blue `#3c6fd1`) and the Family calendar (orange `#d9772e`), and today and tomorrow's events from the mockup. It also includes one 06:30 event, one overlapping pair, one three-day all-day event, eight photos (two with `takenAt: null` and `place: null`), seven shopping items, three tasks, four lamp plugs across Living room ×2, Office and Bedroom, a speaker, two Claude sessions (one `waiting`), and usage at 42% and 61%.
  - `mockApi(): VitePlugin`, which handles every endpoint in the contract against one in-memory state. It honours query flags: `?fail=1` makes `/api/state` return 503, and `?nulls=1` returns `weather`, `speaker` and `claude.usage` as `null`.
  - `api.getState(): Promise<State>`; `api.act(method, path, body): Promise<State>`.
  - `createStore({ load: () => Promise<State>, intervalMs = 15000 })` returns `{ get(): {state: State|null, stale: boolean, error: string|null}, subscribe(fn): unsubscribe, refresh(): Promise<void>, set(state: State): void }`.
- Photo fixtures are generated as solid-colour or gradient JPEG data URLs, or served from `dev/photos/` with local placeholder images. No remote URLs.

- [ ] **Step 1: Write failing tests.**
  - The store emits a state after the first `refresh`.
  - When a later `load` rejects, `get().state` keeps the previous state, `stale === true`, and `error` is set.
  - A successful load clears `stale`.
  - `set()` notifies subscribers.
  - For the mock API, calling the plugin's request handler directly: `PATCH /api/shopping/items/:id {checked:true}` returns a state with that item checked. `POST /api/tasks` adds a task. An unknown task id returns 404 `{error}`.
- [ ] **Step 2: Run** `npx vitest run test/store.test.js test/mock-api.test.js`. Expected: FAIL.
- [ ] **Step 3: Implement** the four modules and register the plugin.
- [ ] **Step 4: Run the tests**, then run `npm run dev` and `curl -s localhost:5173/api/state | head -c 300`. Expected: tests PASS, and the JSON starts `{"generatedAt":`.
- [ ] **Step 5: Commit:** `git commit -m "feat(dashboard): mock API, fixtures and polling store"`.

### Task 5: Shell, router, themes and the dim/off overlay

**Files:**
- Create: `dashboard/src/router.js`, `dashboard/src/lib/theme.js`, `dashboard/src/ui/icons.js` (ported), `dashboard/src/css/tokens.css`, `dashboard/src/css/base.css`
- Modify: `dashboard/src/main.js`, `dashboard/index.html`
- Test: `dashboard/test/theme.test.js`, `dashboard/test/shell.test.js`

**Interfaces:**
- Consumes: `createStore`, `api` (Task 4).
- Produces:
  - `themeFor(now: Date, sunrise: Date|null, sunset: Date|null): 'paper'|'night'`. When `weather` is null, the fallback is sunrise 07:00 and sunset 19:00.
  - `createRouter(root: HTMLElement, views: Record<string, View>)` returns `{ go(name), current() }`.
  - `View = { mount(el: HTMLElement, ctx: Ctx): void, update(state: State, ctx: Ctx): void }`, where `Ctx = { now(): Date, act(method, path, body): Promise<void>, go(name): void, toast(msg: string): void }`.
  - Idle return: after 120 s with no touch, `go('home')`.
  - Overlay: `screen.mode === 'dim'` shows a black overlay at 0.75 opacity. `'off'` shows it at 1.0, and the next tap calls `POST /api/screen/wake` and is swallowed, so it doesn't press whatever is underneath. `'on'` hides it.
  - Stale marker: when the store is `stale`, a small "Offline · last updated 8:42am" pill appears top right.
  - Theme override (spec §6): tapping the rail clock flips the theme. The override lasts until the next sunrise or sunset, then automatic switching resumes. `themeFor` stays pure; the override lives in `main.js` as `{theme, until: Date}`.

- [ ] **Step 1: Write failing tests.**
  - `themeFor` returns `paper` at 12:00, `night` at 20:00 with sunset 18:10, `paper` at 07:30 with sunrise 07:25, and `night` at 06:00 when both are null.
  - Shell test (jsdom): with `screen.mode: 'off'`, `#overlay` has class `is-off`. A click on it calls `act('POST', '/api/screen/wake')` and doesn't call the underlying view's click handler.
  - Router: `go('shopping')` adds `is-active` to that section only.
  - Stale state shows the pill text, including the last-updated time.
  - At 12:00, a click on the rail clock sets `data-theme="night"`. With the clock advanced past that day's sunset and then the next sunrise, the theme is `paper` again.
- [ ] **Step 2: Run** `npx vitest run test/theme.test.js test/shell.test.js`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `tokens.css` defines `:root[data-theme="paper"]` and `:root[data-theme="night"]` token sets. Take the colours from the approved mockup's `.theme-paper` and `.theme-night` variables, with fonts `--display: 'DM Serif Display'` and `--sans: 'Archivo Variable'`.
  - Theme changes add `theme-fading` for 3 s (opacity cross-fade on `.views`).
  - The rail sits on the left, 96 px wide, with Wes's icons. The rail clock shows `fmtTime`.
  - `main.js` ticks every 30 s to re-render time-dependent bits and re-evaluate the theme.
- [ ] **Step 4: Run the tests and** `npm run build`. Expected: PASS, with 0 compat violations.
- [ ] **Step 5: Commit:** `git commit -m "feat(dashboard): shell, router, day/night themes, dim/off overlay"`.

### Task 6: Home screen (command centre)

**Files:**
- Create: `dashboard/src/views/home.js`, `dashboard/src/lib/captions.js`, `dashboard/src/ui/slideshow.js` (ported), `dashboard/src/css/views/home.css`
- Test: `dashboard/test/captions.test.js`, `dashboard/test/home.test.js`

**Interfaces:**
- Consumes: `layoutDay`, `allDayOn`, `nextEvent`, `leaveBy`, the time formatters, `View`/`Ctx`.
- Produces:
  - `photoCaption(takenAt: Date|null, place: string|null, now: Date): {kicker: string|null, place: string|null}|null`. The kicker is `'ON THIS DAY · 3 YEARS AGO'` when the month and day match in an earlier year, otherwise `'1 YEAR AGO'` / `'N YEARS AGO'`, and for photos under a year old, `'MARCH 2026'`. It returns `null` when both inputs are null.
  - `createSlideshow(el, { intervalMs = 12000, onChange })` returns `{ setPhotos(photos), start(), stop() }`.

The layout matches the approved mockup's grid: columns `290px 1fr 330px`, rows `205px 1fr 190px`, gap 14 px. The tiles are clock, next-up hero, photo plus plug strip, weather, agenda (Today and Tomorrow on the `GRID`, with hour lines, dashed half-hours, a 1.5 px day divider, a red "now" line on today, faded past events and one-line short events), tasks and shopping duo, and the Claude tile. Every tile except the plug buttons navigates to its full screen on tap. A plug button toggles via `POST /api/plugs/:id {on}`.

- [ ] **Step 1: Write failing tests.**
  - Captions: 22 Oct 2025 seen on 22 Oct 2026 gives `'ON THIS DAY · 1 YEAR AGO'`. 3 Mar 2024 gives `'2 YEARS AGO'`. 1 Mar 2026 gives `'MARCH 2026'`. `(null, null)` gives `null`. `(null, 'Whitby')` gives `{kicker: null, place: 'Whitby'}`.
  - Home (jsdom, fixture state, now 08:42 on 22 Oct 2026):
    - The hero shows the next event's title and `Leave by 5:10pm`.
    - The agenda has 12 hour lines (9am–8pm) per day column, and the now line is at `topPct ≈ 5.38`.
    - The Claude tile shows `Needs you` when any session is `waiting` and hides it when none are.
    - With `?nulls`-style state, the weather tile shows `Weather unavailable` and the Claude meters show `Usage unavailable`, with no exception.
    - A 60-character title has an element with computed or inline `text-overflow: ellipsis`.
    - With no events in 48 h, the hero shows `Nothing coming up`.
- [ ] **Step 2: Run** `npx vitest run test/captions.test.js test/home.test.js`. Expected: FAIL.
- [ ] **Step 3: Implement** the view and CSS. Port `slideshow.js` from Wes, trimmed to two `<img>` elements and no captions overlay, since the home view renders captions itself.
- [ ] **Step 4: Run the tests, then `npm run dev`, and check at 1280×800** in Chrome DevTools device mode in both themes (add `?theme=night` to force the theme in dev). Expected: tests PASS, and the view matches the mockup's layout.
- [ ] **Step 5: Commit:** `git commit -m "feat(dashboard): home command-centre view"`.

### Task 7: Calendar screen

**Files:**
- Create: `dashboard/src/views/calendar.js`, `dashboard/src/css/views/calendar.css`
- Test: `dashboard/test/calendar-view.test.js`

**Interfaces:**
- Consumes: `layoutDay`, `allDayOn`, the time helpers.
- Produces: a five-day view (today plus four days) using the same grid styling as the home agenda, with an all-day strip per day, a legend of `State.calendars` (label and colour), and ‹ › buttons that page by five days. The "Today" button returns to the start. Tapping an event opens a sheet with the title, range, location and calendar label.

- [ ] **Step 1: Write failing tests.**
  - Five day columns are rendered, with headers `Today`, `Tomorrow`, then weekday names.
  - The overlapping pair renders with `width: 50%` blocks side by side.
  - The legend lists both calendars.
  - The › button shifts the first header to the date five days ahead.
- [ ] **Step 2: Run** `npx vitest run test/calendar-view.test.js`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit:** `git commit -m "feat(dashboard): five-day calendar screen"`.

### Task 8: Shopping and Tasks screens

**Files:**
- Create: `dashboard/src/views/shopping.js`, `dashboard/src/views/tasks.js`, `dashboard/src/css/views/shopping.css`, `dashboard/src/css/views/tasks.css`
- Test: `dashboard/test/shopping.test.js`, `dashboard/test/tasks.test.js`

**Interfaces:**
- Consumes: `Ctx.act` with the shopping and tasks endpoints from the contract.
- Produces:
  - **Shopping:** unchecked items first, then checked items (faded, struck through) under "Done". Tapping an item calls `PATCH …/items/:id {checked: !checked}`. An add field with an Add button calls `POST …/items {text}`. A row of quick-add chips holds frequent items, taken from checked items' text, deduplicated, up to eight. When `shopping.stale`, an "Out of sync with Keep" note appears. The list scrolls inside its panel.
  - **Tasks:** three columns (Alex, Vicky, Anyone) from `State.people` plus `any`. Each task shows its title and its due time, formatted as `today 6:00pm`, `tomorrow`, or a weekday. Overdue tasks are tinted. Tapping toggles `done` via `PATCH`. A long press (600 ms) offers Delete. An add sheet has fields for title, assignee and a due choice (none / today evening 18:00 / tomorrow / pick time).
  - Text entry depends on the frame having an on-screen keyboard. Quick-add chips and preset due choices must work with no typing.

- [ ] **Step 1: Write failing tests.**
  - Tapping an unchecked item calls `act('PATCH', '/api/shopping/items/<id>', {checked: true})`.
  - With 25 items, the list container has `overflow-y: auto` and the panel height doesn't change.
  - The stale note appears when `stale: true`.
  - The tasks view renders three columns with the right counts.
  - Tapping calls `act('PATCH', '/api/tasks/<id>', {done: true})`.
  - A task due yesterday has class `is-overdue`.
  - Fifteen tasks in one column scroll inside the column.
- [ ] **Step 2: Run** `npx vitest run test/shopping.test.js test/tasks.test.js`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit:** `git commit -m "feat(dashboard): shopping and tasks screens"`.

### Task 9: Photos, Home control and Claude screens

**Files:**
- Create: `dashboard/src/views/photos.js`, `dashboard/src/views/control.js`, `dashboard/src/views/claude.js`, plus a CSS file each
- Test: `dashboard/test/control.test.js`, `dashboard/test/claude.test.js`

**Interfaces:**
- Consumes: `createSlideshow`, `photoCaption`, `Ctx.act`.
- Produces:
  - **Photos:** a full-bleed slideshow (8 s interval) with a caption bottom-left. The rail hides after 5 s and returns on tap.
  - **Control:** plugs grouped by `room`, skipping `hidden` ones. A plug with `confirm: true` asks "Turn off <name>?" before acting. An unreachable plug is greyed with "Offline" and isn't tappable. The speaker card shows title and artist (or "Nothing playing"), a play/pause button (`POST /api/speaker {action}`) and − / + volume in steps of 10 (`{action: 'volume', volume}`). A `null` speaker shows "Speaker unavailable".
  - **Claude:** two usage meters (session and weekly), each with a percentage, a "resets in" countdown and an even-pace marker as in Wes's agents view. When `usage` is null, the meters are replaced by "Usage unavailable". Below is the session list sorted with `waiting` first, showing project, state chip ("Needs you", "Working", "Done") and time in state (`12 min`).

- [ ] **Step 1: Write failing tests.**
  - Control groups four plugs into three rooms. A hidden plug isn't rendered. A confirm plug opens a confirm sheet before any `act` call. An unreachable plug click calls nothing. Volume + at 40 calls `act('POST', '/api/speaker', {action: 'volume', volume: 50})`.
  - Claude: waiting sessions are listed first. `usage: null` shows "Usage unavailable". At 42% with 1h 18m left of a 5 h window, the meter shows `42%` and `resets in 1h 18m`.
- [ ] **Step 2: Run** `npx vitest run test/control.test.js test/claude.test.js`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit:** `git commit -m "feat(dashboard): photos, home control and Claude screens"`.

### Task 10: Screenshots and review with Alex

**Files:**
- Create: `dashboard/scripts/screenshot.mjs`
- Modify: `dashboard/package.json` (`screens` script), `.gitignore` (`dashboard/screenshots/`)

**Interfaces:**
- Consumes: the dev server, plus dev query flags `?view=<name>`, `?theme=paper|night`, `?now=<ISO>` (pins the clock; dev only), `?nulls=1` and `?fail=1`. Add `?view` and `?now` handling to `main.js`, active only in dev builds via `import.meta.env.DEV`.
- Produces: `npm run screens` starts the dev server, then runs headless Chrome at `--window-size=1280,800` for each of the seven views × two themes, plus home with `?nulls=1` and home with `?fail=1`. The PNGs go to `dashboard/screenshots/`.

- [ ] **Step 1: Implement the script.** Use the system Chrome binary (`/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --headless=new --screenshot`), with `?now=2026-10-22T08:42:00+01:00` for the day theme and `T20:15` for night.
- [ ] **Step 2: Run** `npm run screens`. Expected: 16 PNGs, with nothing clipped in any of them. Read each screenshot and fix any overflow, clipped text or theme mismatch before continuing.
- [ ] **Step 3: Run the full suite and build:** `npx vitest run && npm run build`. Expected: all tests PASS, with 0 compat violations.
- [ ] **Step 4: Show Alex the screenshots** (open them, or publish them as an artifact). Record his change requests as new tasks in this plan before closing it.
- [ ] **Step 5: Commit:** `git commit -m "chore(dashboard): screenshot script for visual review"`.
