import { describe, it, expect } from 'vitest';
import {
  fmtTime, fmtHour, fmtRange, fmtDay, fmtDate, fmtCountdown,
  dayStart, addDays, hoursSinceDayStart,
} from '../src/lib/time.js';

describe('formatting', () => {
  it('fmtTime', () => {
    expect(fmtTime(new Date('2026-10-22T08:42:00+01:00'))).toBe('8:42am');
    expect(fmtTime(new Date('2026-10-22T12:00:00+01:00'))).toBe('12:00pm');
    expect(fmtTime(new Date('2026-10-22T17:30:00+01:00'))).toBe('5:30pm');
    expect(fmtTime(new Date('2026-10-22T00:05:00+01:00'))).toBe('12:05am');
  });
  it('fmtHour', () => {
    expect(fmtHour(9)).toBe('9am');
    expect(fmtHour(12)).toBe('12pm');
    expect(fmtHour(0)).toBe('12am');
    expect(fmtHour(15)).toBe('3pm');
  });
  it('fmtRange', () => {
    expect(fmtRange(new Date('2026-10-22T11:30:00+01:00'), new Date('2026-10-22T12:30:00+01:00'))).toBe('11:30am–12:30pm');
  });
  it('fmtDay and fmtDate', () => {
    const d = new Date('2026-10-22T10:00:00+01:00');
    expect(fmtDay(d)).toBe('Thursday');
    expect(fmtDate(d)).toBe('22 October');
  });
  it('fmtCountdown', () => {
    expect(fmtCountdown(38)).toBe('38 min');
    expect(fmtCountdown(528)).toBe('8h 48');
    expect(fmtCountdown(60)).toBe('1h 00');
    expect(fmtCountdown(125)).toBe('2h 05');
    expect(fmtCountdown(37.6)).toBe('38 min');
    expect(fmtCountdown(0)).toBe('0 min');
  });
});

describe('day maths', () => {
  const day = new Date('2026-10-25T00:00:00+01:00');
  it('dayStart', () => {
    const s = dayStart(new Date('2026-10-22T15:45:10+01:00'));
    expect([s.getDate(), s.getHours(), s.getMinutes(), s.getSeconds()]).toEqual([22, 0, 0, 0]);
  });
  it('hoursSinceDayStart across clock change', () => {
    expect(hoursSinceDayStart(new Date('2026-10-25T09:00:00Z'), day)).toBe(9);
    expect(hoursSinceDayStart(new Date('2026-10-25T09:30:00Z'), day)).toBe(9.5);
  });
  it('addDays across clock change', () => {
    expect(addDays(day, 1).getDate()).toBe(26);
    expect(addDays(day, 1).getHours()).toBe(0);
    expect(addDays(day, -1).getDate()).toBe(24);
  });
});
