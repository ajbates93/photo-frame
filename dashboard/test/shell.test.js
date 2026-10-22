import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createStore } from '../src/store.js';
import { boot } from '../src/main.js';
import { makeFixtureState } from '../dev/fixtures.js';

const html = readFileSync(resolve(process.cwd(), 'index.html'), 'utf8');
const body = html.match(/<body>([\s\S]*?)<script/)[1];

function setup({ mode = 'on', weather } = {}) {
  document.body.innerHTML = body;
  const state = makeFixtureState(new Date());
  state.screen = { mode };
  if (weather !== undefined) state.weather = weather;
  const store = createStore({ load: async () => state });
  const api = { act: vi.fn(async () => ({ ...state, screen: { mode: 'on' } })), getState: async () => state };
  const views = Object.fromEntries(['home', 'calendar', 'tasks', 'shopping', 'photos', 'control', 'claude']
    .map((n) => [n, { mount: vi.fn(), update: vi.fn() }]));
  const shell = boot({ doc: document, store, api, views });
  return { shell, store, api, views, state };
}

const flush = async () => { await vi.advanceTimersByTimeAsync(0); };

describe('shell', () => {
  let shell;
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 22, 12, 0));
  });
  afterEach(() => {
    shell?.stop();
    vi.useRealTimers();
    document.documentElement.removeAttribute('data-theme');
    document.documentElement.className = '';
  });

  it('go() activates only the named section', () => {
    ({ shell } = setup());
    shell.router.go('shopping');
    const active = [...document.querySelectorAll('.view.is-active')].map((e) => e.dataset.view);
    expect(active).toEqual(['shopping']);
    expect(shell.router.current()).toBe('shopping');
  });

  it('calls hide() on the outgoing view and show() on the incoming one', () => {
    let s;
    ({ shell, ...s } = setup());
    s.views.home.show = vi.fn();
    s.views.home.hide = vi.fn();
    s.views.tasks.show = vi.fn();
    shell.router.go('tasks');
    expect(s.views.home.hide).toHaveBeenCalledTimes(1);
    expect(s.views.tasks.show).toHaveBeenCalledTimes(1);
    shell.router.go('tasks');
    expect(s.views.tasks.show).toHaveBeenCalledTimes(1);
    shell.router.go('home');
    expect(s.views.home.show).toHaveBeenCalledTimes(1);
  });

  it('off overlay wakes once on a tap, cancels no events, and hides the view underneath from clicks', async () => {
    let s;
    ({ shell, ...s } = setup({ mode: 'off' }));
    await flush();
    const overlay = document.getElementById('overlay');
    expect(overlay.classList.contains('is-off')).toBe(true);
    const underneath = vi.fn();
    document.querySelector('[data-view="home"]').addEventListener('click', underneath);
    const evs = ['touchstart', 'touchend', 'pointerdown', 'pointerup', 'mousedown', 'mouseup', 'click'].map((t) => {
      const e = new Event(t, { bubbles: true, cancelable: true });
      overlay.dispatchEvent(e);
      return e;
    });
    await flush();
    expect(evs.every((e) => !e.defaultPrevented)).toBe(true);
    expect(underneath).not.toHaveBeenCalled();
    expect(s.api.act).toHaveBeenCalledTimes(1);
    expect(s.api.act).toHaveBeenCalledWith('POST', '/api/screen/wake', undefined);
    expect(overlay.classList.contains('is-off')).toBe(false);
  });

  it('stop() unsubscribes from the store and ends rendering', async () => {
    let s;
    ({ shell, ...s } = setup());
    await flush();
    let renders = 0;
    s.views.home.update.mockImplementation(() => { renders += 1; });
    shell.stop();
    await s.store.refresh();
    await vi.advanceTimersByTimeAsync(120000);
    expect(renders).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('dim overlay catches the first tap: wakes once and nothing underneath receives it', async () => {
    let s;
    ({ shell, ...s } = setup({ mode: 'dim' }));
    await flush();
    const overlay = document.getElementById('overlay');
    expect(overlay.classList.contains('is-dim')).toBe(true);
    const underneath = vi.fn();
    document.querySelector('[data-view="home"]').addEventListener('click', underneath);
    const evs = ['touchstart', 'touchend', 'pointerdown', 'pointerup', 'mousedown', 'mouseup', 'click'].map((t) => {
      const e = new Event(t, { bubbles: true, cancelable: true });
      overlay.dispatchEvent(e);
      return e;
    });
    await flush();
    expect(evs.every((e) => !e.defaultPrevented)).toBe(true);
    expect(underneath).not.toHaveBeenCalled();
    expect(s.api.act).toHaveBeenCalledTimes(1);
    expect(s.api.act).toHaveBeenCalledWith('POST', '/api/screen/wake', undefined);
    expect(overlay.classList.contains('is-dim')).toBe(false);
  });

  it('does not return home on idle while photos is showing, but still does from tasks', async () => {
    ({ shell } = setup());
    shell.router.go('photos');
    await vi.advanceTimersByTimeAsync(300000);
    expect(shell.router.current()).toBe('photos');
    shell.router.go('tasks');
    document.dispatchEvent(new Event('pointerdown'));
    await vi.advanceTimersByTimeAsync(121000);
    expect(shell.router.current()).toBe('home');
  });

  it('shows an offline pill with the last updated time when stale', async () => {
    let s;
    ({ shell, ...s } = setup());
    await flush();
    expect(document.getElementById('stale').classList.contains('is-visible')).toBe(false);
    // a fresh shell whose store holds an 8:42am state and then fails to refresh
    shell.stop();
    document.body.innerHTML = body;
    const failing = createStore({ load: async () => { throw new Error('down'); } });
    failing.set({ ...s.state, generatedAt: new Date(2026, 9, 22, 8, 42).toISOString() });
    shell = boot({ doc: document, store: failing, api: s.api, views: s.views });
    await flush();
    expect(document.getElementById('stale').textContent).toBe('Offline · last updated 8:42am');
    expect(document.getElementById('stale').classList.contains('is-visible')).toBe(true);
  });

  it('clock tap flips the theme until the boundary, then auto resumes', async () => {
    ({ shell } = setup({ weather: null }));
    await flush();
    const root = document.documentElement;
    expect(root.dataset.theme).toBe('paper');
    document.getElementById('railClock').click();
    expect(root.dataset.theme).toBe('night');
    expect(root.classList.contains('theme-fading')).toBe(true);
    await vi.advanceTimersByTimeAsync(4000);
    expect(root.classList.contains('theme-fading')).toBe(false);
    vi.setSystemTime(new Date(2026, 9, 22, 12, 30));
    await vi.advanceTimersByTimeAsync(30000);
    expect(root.dataset.theme).toBe('night'); // override still held
    vi.setSystemTime(new Date(2026, 9, 22, 19, 5)); // past sunset: automatic night
    await vi.advanceTimersByTimeAsync(30000);
    expect(root.dataset.theme).toBe('night');
    vi.setSystemTime(new Date(2026, 9, 23, 7, 5)); // past next sunrise
    await vi.advanceTimersByTimeAsync(30000);
    expect(root.dataset.theme).toBe('paper');
  });

  it('clock tap at night holds paper until sunrise', async () => {
    vi.setSystemTime(new Date(2026, 9, 22, 21, 0));
    ({ shell } = setup({ weather: null }));
    await flush();
    expect(document.documentElement.dataset.theme).toBe('night');
    document.getElementById('railClock').click();
    expect(document.documentElement.dataset.theme).toBe('paper');
    vi.setSystemTime(new Date(2026, 9, 23, 7, 5));
    await vi.advanceTimersByTimeAsync(30000);
    expect(document.documentElement.dataset.theme).toBe('paper');
  });

  it('returns home after 120 s without input, and input resets the timer', async () => {
    ({ shell } = setup());
    shell.router.go('claude');
    await vi.advanceTimersByTimeAsync(100000);
    document.dispatchEvent(new Event('pointerdown'));
    await vi.advanceTimersByTimeAsync(100000);
    expect(shell.router.current()).toBe('claude');
    await vi.advanceTimersByTimeAsync(21000);
    expect(shell.router.current()).toBe('home');
  });

  it('ctx.act sets the store on success and toasts on failure without throwing', async () => {
    let s;
    ({ shell, ...s } = setup());
    await flush();
    const next = { ...s.state, tasks: [] };
    s.api.act.mockResolvedValueOnce(next);
    await expect(shell.ctx.act('PATCH', '/api/tasks/x', { done: true })).resolves.toBe(true);
    expect(s.store.get().state).toBe(next);
    s.api.act.mockRejectedValueOnce(new Error('Nope'));
    await expect(shell.ctx.act('POST', '/api/tasks', {})).resolves.toBe(false);
    expect(document.getElementById('toasts').textContent).toBe('Nope');
    await vi.advanceTimersByTimeAsync(3100);
    expect(document.getElementById('toasts').textContent).toBe('');
  });
});

describe('shell view isolation', () => {
  afterEach(() => { vi.useRealTimers(); document.body.innerHTML = ''; });

  it('a throwing view does not stop the others or turn a successful act into false', async () => {
    vi.useFakeTimers();
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    document.body.innerHTML = body;
    const state = makeFixtureState(new Date());
    const store = createStore({ load: async () => state });
    const api = { act: vi.fn(async () => ({ ...state, tasks: [] })), getState: async () => state };
    const views = Object.fromEntries(['home', 'calendar', 'tasks', 'shopping', 'photos', 'control', 'claude']
      .map((n) => [n, { mount: vi.fn(), update: vi.fn() }]));
    views.home.update.mockImplementation(() => { throw new Error('home broke'); });
    const shell = boot({ doc: document, store, api, views });
    await vi.advanceTimersByTimeAsync(0);
    expect(views.calendar.update).toHaveBeenCalled();
    const before = views.claude.update.mock.calls.length;
    await expect(shell.ctx.act('PATCH', '/api/tasks/x', { done: true })).resolves.toBe(true);
    expect(views.claude.update.mock.calls.length).toBeGreaterThan(before);
    expect(spy).toHaveBeenCalled();
    shell.stop();
    spy.mockRestore();
  });

  it('a throwing offline() does not stop the other placeholders', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    document.body.innerHTML = body;
    const store = createStore({ load: async () => { throw new Error('down'); } });
    const views = Object.fromEntries(['home', 'calendar', 'tasks', 'shopping', 'photos', 'control', 'claude']
      .map((n) => [n, { mount: vi.fn(), update: vi.fn() }]));
    views.home.offline = vi.fn(() => { throw new Error('offline broke'); });
    const shell = boot({ doc: document, store, api: { act: vi.fn(), getState: vi.fn() }, views });
    await store.refresh();
    expect(document.querySelector('[data-view="tasks"] .unavailable')).not.toBeNull();
    shell.stop();
    spy.mockRestore();
  });
});

describe('shell offline placeholders', () => {
  afterEach(() => { document.body.innerHTML = ''; });

  it('shows the unreachable message in views without state and clears it on recovery', async () => {
    document.body.innerHTML = body;
    let fail = true;
    const state = makeFixtureState(new Date());
    const api = { getState: async () => state, act: vi.fn() };
    const store = createStore({ load: async () => { if (fail) throw new Error('down'); return state; } });
    const views = Object.fromEntries(['home', 'calendar', 'tasks', 'shopping', 'photos', 'control', 'claude']
      .map((n) => [n, { mount: vi.fn(), update: vi.fn() }]));
    const shell = boot({ doc: document, store, api, views });
    await store.refresh();
    const el = document.querySelector('[data-view="tasks"]');
    expect(el.querySelector('.unavailable').textContent).toContain("Can't reach the home server");
    fail = false;
    await store.refresh();
    expect(document.querySelector('.unavailable')).toBeNull();
    shell.stop();
  });
});

describe('stale pill', () => {
  it('never takes taps meant for the controls underneath', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/css/base.css'), 'utf8');
    const rule = css.match(/#stale\s*\{([^}]*)\}/)[1];
    expect(rule).toMatch(/pointer-events:\s*none/);
  });
});
