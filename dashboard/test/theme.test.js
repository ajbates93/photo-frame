import { themeFor, nextBoundary } from '../src/lib/theme.js';

const at = (h, m = 0) => new Date(2026, 9, 22, h, m);

describe('themeFor', () => {
  it('is paper at midday', () => {
    expect(themeFor(at(12), at(7, 25), at(18, 10))).toBe('paper');
  });
  it('is night after sunset', () => {
    expect(themeFor(at(20), at(7, 25), at(18, 10))).toBe('night');
  });
  it('is paper just after sunrise', () => {
    expect(themeFor(at(7, 30), at(7, 25), at(18, 10))).toBe('paper');
  });
  it('falls back to 07:00 / 19:00 when sun times are null', () => {
    expect(themeFor(at(6), null, null)).toBe('night');
    expect(themeFor(at(12), null, null)).toBe('paper');
    expect(themeFor(at(19, 30), null, null)).toBe('night');
  });
});

describe('nextBoundary', () => {
  it('is the sunset by day, and tomorrow\'s sunrise after dark', () => {
    expect(nextBoundary(at(12), at(7, 25), at(18, 10))).toEqual(at(18, 10));
    expect(nextBoundary(at(20), at(7, 25), at(18, 10))).toEqual(new Date(2026, 9, 23, 7, 25));
  });
});
