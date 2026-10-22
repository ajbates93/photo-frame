import { describe, it, expect } from 'vitest';
import { GRID, layoutDay, allDayOn, nextEvent, leaveBy } from '../src/lib/calendar.js';

const d = (y, m, day, h = 0, min = 0) => new Date(y, m - 1, day, h, min);
const ev = (id, start, end, extra = {}) => ({
  id, calendarId: 'alex', title: id, start: start.toISOString(), end: end.toISOString(),
  allDay: false, location: null, travelMins: null, ...extra,
});
const DAY = d(2026, 10, 22);
const NOW = d(2026, 10, 22, 8, 0);

describe('layoutDay', () => {
  it('positions a short event as percentages of the grid', () => {
    const [b] = layoutDay([ev('a', d(2026, 10, 22, 9), d(2026, 10, 22, 9, 30))], DAY, NOW);
    expect(GRID).toEqual({ startHour: 8, endHour: 21 });
    expect(b.topPct).toBeCloseTo(7.69, 2);
    expect(b.heightPct).toBeCloseTo(3.85, 2);
    expect(b.short).toBe(true);
    expect(b.clampedStart).toBe(false);
    expect(b.clampedEnd).toBe(false);
  });

  it('puts overlapping events in side-by-side columns', () => {
    const bs = layoutDay([
      ev('a', d(2026, 10, 22, 17, 30), d(2026, 10, 22, 18, 15)),
      ev('b', d(2026, 10, 22, 17, 45), d(2026, 10, 22, 19)),
    ], DAY, NOW);
    expect(bs.map((b) => b.cols)).toEqual([2, 2]);
    expect(bs.map((b) => b.col).sort()).toEqual([0, 1]);
  });

  it('clamps an event before the grid to the top', () => {
    const bs = layoutDay([ev('a', d(2026, 10, 22, 6, 30), d(2026, 10, 22, 7, 15))], DAY, NOW);
    expect(bs).toHaveLength(1);
    expect(bs[0].topPct).toBe(0);
    expect(bs[0].heightPct).toBe(3);
    expect(bs[0].clampedStart).toBe(true);
  });

  it('clamps an event after the grid to the bottom edge', () => {
    const bs = layoutDay([ev('a', d(2026, 10, 22, 22), d(2026, 10, 22, 23))], DAY, NOW);
    expect(bs).toHaveLength(1);
    expect(bs[0].clampedStart).toBe(true);
    expect(bs[0].topPct).toBe(97);
    expect(bs[0].heightPct).toBe(3);
  });

  it('clips a partially outside event and flags the clipped edge', () => {
    const [b] = layoutDay([ev('a', d(2026, 10, 22, 7), d(2026, 10, 22, 9))], DAY, NOW);
    expect(b.topPct).toBe(0);
    expect(b.heightPct).toBeCloseTo(7.69, 2);
    expect(b.clampedStart).toBe(true);
    expect(b.clampedEnd).toBe(false);
    const [c] = layoutDay([ev('b', d(2026, 10, 22, 20), d(2026, 10, 22, 22))], DAY, NOW);
    expect(c.clampedEnd).toBe(true);
    expect(c.clampedStart).toBe(false);
    expect(c.topPct + c.heightPct).toBeCloseTo(100, 5);
  });

  it('shows a midnight-spanning event on both days', () => {
    const e = ev('a', d(2026, 10, 22, 23, 30), d(2026, 10, 23, 0, 30));
    expect(layoutDay([e], DAY, NOW)).toHaveLength(1);
    expect(layoutDay([e], d(2026, 10, 23), NOW)).toHaveLength(1);
    expect(layoutDay([e], d(2026, 10, 24), NOW)).toHaveLength(0);
  });

  it('ignores all-day events', () => {
    const e = ev('a', d(2026, 10, 22), d(2026, 10, 23), { allDay: true });
    expect(layoutDay([e], DAY, NOW)).toHaveLength(0);
  });

  it('marks past when end <= now', () => {
    const e = ev('a', d(2026, 10, 22, 9), d(2026, 10, 22, 10));
    expect(layoutDay([e], DAY, d(2026, 10, 22, 10))[0].past).toBe(true);
    expect(layoutDay([e], DAY, d(2026, 10, 22, 9, 59))[0].past).toBe(false);
    expect(layoutDay([e], DAY, d(2026, 10, 22, 10))[0].short).toBe(false);
  });

  it('is correct on the clock-change day', () => {
    const day = d(2026, 10, 25);
    const [b] = layoutDay([ev('a', d(2026, 10, 25, 9), d(2026, 10, 25, 9, 30))], day, d(2026, 10, 25, 8));
    expect(b.topPct).toBeCloseTo(7.69, 2);
  });
});

describe('layoutDay overlap columns', () => {
  const cols = (specs) => {
    const bs = layoutDay(
      specs.map(([id, h1, m1, h2, m2]) => ev(id, d(2026, 10, 22, h1, m1), d(2026, 10, 22, h2, m2))),
      DAY, NOW,
    );
    return Object.fromEntries(bs.map((b) => [b.event.id, [b.col, b.cols]]));
  };

  it('reuses a free column within a transitive cluster', () => {
    expect(cols([['A', 9, 0, 11, 0], ['B', 10, 0, 12, 0], ['C', 11, 30, 13, 0]]))
      .toEqual({ A: [0, 2], B: [1, 2], C: [0, 2] });
  });

  it('keeps separate clusters independent', () => {
    expect(cols([['A', 9, 0, 10, 0], ['B', 9, 30, 10, 30], ['C', 14, 0, 15, 0]]))
      .toEqual({ A: [0, 2], B: [1, 2], C: [0, 1] });
  });

  it('does not merge back-to-back events', () => {
    expect(cols([['A', 9, 0, 10, 0], ['B', 10, 0, 11, 0]]))
      .toEqual({ A: [0, 1], B: [0, 1] });
  });

  it('gives two blocks clamped to the top edge their own columns', () => {
    const bs = layoutDay([
      ev('gym', d(2026, 10, 22, 6, 30), d(2026, 10, 22, 7, 15)),
      ev('dog', d(2026, 10, 22, 7, 20), d(2026, 10, 22, 7, 50)),
    ], DAY, NOW);
    bs.forEach((b) => expect(b.topPct).toBe(0));
    expect(bs.map((b) => b.cols)).toEqual([2, 2]);
    expect(bs.map((b) => b.col).sort()).toEqual([0, 1]);
  });

  it('gives two blocks clamped to the bottom edge their own columns', () => {
    const bs = layoutDay([
      ev('a', d(2026, 10, 22, 21, 30), d(2026, 10, 22, 22, 15)),
      ev('b', d(2026, 10, 22, 22, 30), d(2026, 10, 22, 23, 30)),
    ], DAY, NOW);
    bs.forEach((b) => expect(b.topPct).toBe(97));
    expect(bs.map((b) => b.cols)).toEqual([2, 2]);
    expect(bs.map((b) => b.col).sort()).toEqual([0, 1]);
  });

  it('uses three columns for three mutually overlapping events', () => {
    expect(cols([['A', 9, 0, 11, 0], ['B', 9, 30, 11, 0], ['C', 10, 0, 11, 0]]))
      .toEqual({ A: [0, 3], B: [1, 3], C: [2, 3] });
  });
});

describe('allDayOn', () => {
  it('covers [start, end) by date', () => {
    const e = ev('a', d(2026, 10, 26), d(2026, 10, 29), { allDay: true });
    for (const n of [26, 27, 28]) expect(allDayOn([e], d(2026, 10, n, 12))).toEqual([e]);
    expect(allDayOn([e], d(2026, 10, 29))).toEqual([]);
    expect(allDayOn([e], d(2026, 10, 25))).toEqual([]);
  });

  it('excludes timed events', () => {
    expect(allDayOn([ev('a', d(2026, 10, 22, 9), d(2026, 10, 22, 10))], DAY)).toEqual([]);
  });
});

describe('nextEvent', () => {
  const tomorrow9 = ev('t', d(2026, 10, 23, 9), d(2026, 10, 23, 10));
  it('finds tomorrow at 23:59', () => {
    expect(nextEvent([tomorrow9], d(2026, 10, 22, 23, 59))).toBe(tomorrow9);
  });
  it('finds tomorrow at 18:00 when nothing is left today', () => {
    const past = ev('p', d(2026, 10, 22, 9), d(2026, 10, 22, 10));
    expect(nextEvent([past, tomorrow9], d(2026, 10, 22, 18))).toBe(tomorrow9);
  });
  it('returns null beyond 48 h', () => {
    expect(nextEvent([ev('f', d(2026, 10, 25, 9), d(2026, 10, 25, 10))], d(2026, 10, 22, 8))).toBeNull();
  });
  it('skips all-day events and picks the earliest', () => {
    const allDay = ev('x', d(2026, 10, 22, 12), d(2026, 10, 23), { allDay: true });
    const a = ev('a', d(2026, 10, 22, 15), d(2026, 10, 22, 16));
    const b = ev('b', d(2026, 10, 22, 13), d(2026, 10, 22, 14));
    expect(nextEvent([allDay, a, b], NOW)).toBe(b);
  });
});

describe('leaveBy', () => {
  it('subtracts travel minutes', () => {
    const t = leaveBy(ev('a', d(2026, 10, 22, 17, 30), d(2026, 10, 22, 18), { travelMins: 20 }));
    expect(t.getTime()).toBe(d(2026, 10, 22, 17, 10).getTime());
  });
  it('is null without travelMins', () => {
    expect(leaveBy(ev('a', d(2026, 10, 22, 17, 30), d(2026, 10, 22, 18)))).toBeNull();
  });
});
