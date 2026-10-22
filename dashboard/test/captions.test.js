import { photoCaption } from '../src/lib/captions.js';

const now = new Date(2026, 9, 22, 12, 0);

describe('photoCaption', () => {
  it('flags the same day in an earlier year', () => {
    expect(photoCaption(new Date(2025, 9, 22), 'Seaside', now))
      .toEqual({ kicker: 'ON THIS DAY · 1 YEAR AGO', place: 'Seaside' });
    expect(photoCaption(new Date(2023, 9, 22), null, now).kicker).toBe('ON THIS DAY · 3 YEARS AGO');
  });
  it('counts whole years otherwise', () => {
    expect(photoCaption(new Date(2024, 2, 3), null, now).kicker).toBe('2 YEARS AGO');
    expect(photoCaption(new Date(2025, 5, 1), null, now).kicker).toBe('1 YEAR AGO');
  });
  it('uses the month for photos under a year old', () => {
    expect(photoCaption(new Date(2026, 2, 1), null, now).kicker).toBe('MARCH 2026');
    expect(photoCaption(new Date(2025, 10, 5), null, now).kicker).toBe('NOVEMBER 2025');
  });
  it('handles missing data', () => {
    expect(photoCaption(null, null, now)).toBeNull();
    expect(photoCaption(null, 'Whitby', now)).toEqual({ kicker: null, place: 'Whitby' });
  });
});
