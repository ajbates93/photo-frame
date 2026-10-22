import { dayStart, addDays, hoursSinceDayStart } from './time.js';

export const GRID = { startHour: 8, endHour: 21 };

const MIN_HEIGHT_PCT = 3;
const SHORT_MINS = 60;
const LOOKAHEAD_MS = 48 * 3600 * 1000;

const toDate = (v) => (v instanceof Date ? v : new Date(v));

function layoutOne(event, start, end, day, now, grid) {
  const span = grid.endHour - grid.startHour;
  const s = hoursSinceDayStart(start, day);
  const e = hoursSinceDayStart(end, day);
  const pct = (h) => ((h - grid.startHour) / span) * 100;

  let topPct;
  let heightPct;
  let clampedStart = false;
  let clampedEnd = false;

  if (e <= grid.startHour) {
    topPct = 0;
    heightPct = MIN_HEIGHT_PCT;
    clampedStart = true;
  } else if (s >= grid.endHour) {
    topPct = 100 - MIN_HEIGHT_PCT;
    heightPct = MIN_HEIGHT_PCT;
    clampedStart = true;
  } else {
    clampedStart = s < grid.startHour;
    clampedEnd = e > grid.endHour;
    const top = pct(Math.max(s, grid.startHour));
    const bottom = pct(Math.min(e, grid.endHour));
    topPct = top;
    heightPct = Math.max(bottom - top, MIN_HEIGHT_PCT);
    if (topPct + heightPct > 100) topPct = 100 - heightPct;
  }

  return {
    event,
    topPct,
    heightPct,
    col: 0,
    cols: 1,
    short: (end - start) / 60000 < SHORT_MINS,
    past: end <= now,
    clampedStart,
    clampedEnd,
    _start: start,
    _end: end,
  };
}

// Columns are assigned on the displayed intervals (clamped top/height), so blocks
// pinned to the same grid edge never hide each other.
const EPS = 1e-6;
const top = (b) => b.topPct;
const bottom = (b) => b.topPct + b.heightPct;

function assignColumns(blocks) {
  blocks.sort((a, b) => top(a) - top(b) || bottom(a) - bottom(b) || a._start - b._start);
  let cluster = [];
  let clusterEnd = -Infinity;
  const flush = () => {
    const cols = cluster.reduce((m, b) => Math.max(m, b.col + 1), 1);
    cluster.forEach((b) => { b.cols = cols; });
    cluster = [];
  };
  for (const b of blocks) {
    if (cluster.length && top(b) >= clusterEnd - EPS) {
      flush();
      clusterEnd = -Infinity;
    }
    const taken = new Set(
      cluster.filter((o) => bottom(o) > top(b) + EPS).map((o) => o.col),
    );
    let col = 0;
    while (taken.has(col)) col += 1;
    b.col = col;
    cluster.push(b);
    clusterEnd = Math.max(clusterEnd, bottom(b));
  }
  flush();
}

export function layoutDay(events, day, now, grid = GRID) {
  const from = dayStart(day);
  const to = addDays(day, 1);
  const blocks = [];
  for (const event of events) {
    if (event.allDay) continue;
    const start = toDate(event.start);
    const end = toDate(event.end);
    if (!(start < to && end > from)) continue;
    blocks.push(layoutOne(event, start, end, from, now, grid));
  }
  assignColumns(blocks);
  return blocks.map(({ _start, _end, ...b }) => b);
}

export function allDayOn(events, day) {
  const d = dayStart(day);
  return events.filter((event) => {
    if (!event.allDay) return false;
    const first = dayStart(toDate(event.start));
    let last = dayStart(toDate(event.end));
    if (last <= first) last = addDays(first, 1);
    return first <= d && d < last;
  });
}

export function nextEvent(events, now) {
  const limit = now.getTime() + LOOKAHEAD_MS;
  let best = null;
  let bestStart = Infinity;
  for (const event of events) {
    if (event.allDay) continue;
    const s = toDate(event.start).getTime();
    if (s > now.getTime() && s <= limit && s < bestStart) {
      best = event;
      bestStart = s;
    }
  }
  return best;
}

export function leaveBy(event) {
  if (event.travelMins == null) return null;
  return new Date(toDate(event.start).getTime() - event.travelMins * 60000);
}
