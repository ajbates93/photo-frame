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

  it('off overlay is swallowed and wakes the screen', async () => {
    let s;
    ({ shell, ...s } = setup({ mode: 'off' }));
    await flush();
    const overlay = document.getElementById('overlay');
    expect(overlay.classList.contains('is-off')).toBe(true);
    const underneath = vi.fn();
    const btn = document.querySelector('[data-view="home"]');
    btn.addEventListener('click', underneath);
    btn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await flush();
    expect(underneath).not.toHaveBeenCalled();
    expect(s.api.act).toHaveBeenCalledWith('POST', '/api/screen/wake', undefined);
    expect(overlay.classList.contains('is-off')).toBe(false);
  });

  it('dim overlay does not swallow taps', async () => {
    let s;
    ({ shell, ...s } = setup({ mode: 'dim' }));
    await flush();
    expect(document.getElementById('overlay').classList.contains('is-dim')).toBe(true);
    const underneath = vi.fn();
    const el = document.querySelector('[data-view="home"]');
    el.addEventListener('click', underneath);
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(underneath).toHaveBeenCalled();
    expect(s.api.act).not.toHaveBeenCalled();
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
    await shell.ctx.act('PATCH', '/api/tasks/x', { done: true });
    expect(s.store.get().state).toBe(next);
    s.api.act.mockRejectedValueOnce(new Error('Nope'));
    await expect(shell.ctx.act('POST', '/api/tasks', {})).resolves.toBeUndefined();
    expect(document.getElementById('toasts').textContent).toBe('Nope');
    await vi.advanceTimersByTimeAsync(3100);
    expect(document.getElementById('toasts').textContent).toBe('');
  });
});
