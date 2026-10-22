import { createStore } from '../src/store.js';
import { api, REQUEST_TIMEOUT_MS } from '../src/api.js';

describe('store', () => {
  it('emits a state after the first refresh', async () => {
    const store = createStore({ load: async () => ({ generatedAt: 'a' }) });
    const seen = [];
    const off = store.subscribe((s) => seen.push(s));
    expect(store.get().state).toBeNull();
    await store.refresh();
    expect(seen.at(-1).state).toEqual({ generatedAt: 'a' });
    expect(store.get()).toEqual({ state: { generatedAt: 'a' }, stale: false, error: null });
    off();
  });

  it('keeps the previous state and flags stale when a later load rejects, then recovers', async () => {
    let n = 0;
    const store = createStore({
      load: async () => {
        n += 1;
        if (n === 2) throw new Error('boom');
        return { generatedAt: `g${n}` };
      },
    });
    await store.refresh();
    await store.refresh();
    expect(store.get()).toEqual({ state: { generatedAt: 'g1' }, stale: true, error: 'boom' });
    await store.refresh();
    expect(store.get()).toEqual({ state: { generatedAt: 'g3' }, stale: false, error: null });
  });

  it('set() notifies subscribers and unsubscribe stops notifications', () => {
    const store = createStore({ load: async () => ({}) });
    const fn = vi.fn();
    const off = store.subscribe(fn);
    store.set({ generatedAt: 'x' });
    expect(fn).toHaveBeenCalledTimes(1);
    expect(fn.mock.calls[0][0].state).toEqual({ generatedAt: 'x' });
    off();
    store.set({ generatedAt: 'y' });
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('polls on the interval while subscribed', async () => {
    vi.useFakeTimers();
    const load = vi.fn(async () => ({}));
    const store = createStore({ load, intervalMs: 1000 });
    const off = store.subscribe(() => {});
    await vi.advanceTimersByTimeAsync(2100);
    expect(load).toHaveBeenCalledTimes(2);
    off();
    await vi.advanceTimersByTimeAsync(3000);
    expect(load).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it('ignores a non-object load result and keeps the last good state', async () => {
    let n = 0;
    const store = createStore({ load: async () => (++n === 1 ? { generatedAt: 'ok' } : null) });
    await store.refresh();
    await store.refresh();
    expect(store.get()).toMatchObject({ state: { generatedAt: 'ok' }, stale: true });
  });

  it('discards an older in-flight load that resolves after set()', async () => {
    let resolve;
    const store = createStore({ load: () => new Promise((r) => { resolve = r; }) });
    const p = store.refresh();
    store.set({ generatedAt: 'newer' });
    resolve({ generatedAt: 'older' });
    await p;
    expect(store.get().state).toEqual({ generatedAt: 'newer' });
  });

  it('does not start a second poll while a load is still in flight', async () => {
    vi.useFakeTimers();
    let resolve;
    const load = vi.fn(() => new Promise((r) => { resolve = r; }));
    const store = createStore({ load, intervalMs: 1000 });
    const off = store.subscribe(() => {});
    await vi.advanceTimersByTimeAsync(3500);
    expect(load).toHaveBeenCalledTimes(1);
    resolve({ generatedAt: 'a' });
    await vi.advanceTimersByTimeAsync(1000);
    expect(load).toHaveBeenCalledTimes(2);
    off();
    vi.useRealTimers();
  });

  it('keeps notifying other subscribers when one throws', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const store = createStore({ load: async () => ({}) });
    const after = vi.fn();
    const offA = store.subscribe(() => { throw new Error('bad view'); });
    const offB = store.subscribe(after);
    expect(() => store.set({ generatedAt: 'x' })).not.toThrow();
    expect(after).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalled();
    offA(); offB();
    spy.mockRestore();
  });
});

describe('api timeout', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

  it('rejects a hung request after the timeout so the store goes stale', async () => {
    vi.useFakeTimers();
    let signal = null;
    vi.stubGlobal('fetch', vi.fn((path, init) => { signal = init.signal; return new Promise(() => {}); }));
    expect(REQUEST_TIMEOUT_MS).toBe(8000);
    const store = createStore({ load: () => api.getState() });
    const p = store.refresh();
    await vi.advanceTimersByTimeAsync(7900);
    expect(store.get().stale).toBe(false);
    await vi.advanceTimersByTimeAsync(200);
    await p;
    expect(store.get()).toMatchObject({ stale: true, error: 'Request timed out' });
    expect(signal.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('clears its timer when the request completes', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ generatedAt: 'a' }) })));
    await expect(api.getState()).resolves.toEqual({ generatedAt: 'a' });
    expect(vi.getTimerCount()).toBe(0);
  });
});
