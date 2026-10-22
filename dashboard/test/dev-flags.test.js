import { devFlags } from '../src/main.js';

describe('devFlags', () => {
  it('defaults to home with nothing forced', () => {
    expect(devFlags('')).toEqual({ forcedTheme: null, initialView: 'home', now: null, stateSearch: '' });
  });

  it('parses theme, view and now; ignores invalid values', () => {
    const f = devFlags('?theme=night&view=tasks&now=2026-10-22T08:42:00%2B01:00');
    expect(f.forcedTheme).toBe('night');
    expect(f.initialView).toBe('tasks');
    expect(f.now.toISOString()).toBe('2026-10-22T07:42:00.000Z');
    const bad = devFlags('?theme=pink&view=nope&now=garbage');
    expect(bad).toEqual({ forcedTheme: null, initialView: 'home', now: null, stateSearch: '' });
  });

  it('forwards nulls, fail and now onto the state request', () => {
    expect(devFlags('?nulls=1').stateSearch).toBe('?nulls=1');
    expect(devFlags('?fail=1').stateSearch).toBe('?fail=1');
    expect(devFlags('?nulls=0&view=home').stateSearch).toBe('');
    expect(devFlags('?now=2026-10-22T08:42:00%2B01:00').stateSearch)
      .toBe('?now=2026-10-22T08%3A42%3A00%2B01%3A00');
  });
});
