import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createStore } from '../src/store.js';
import { boot } from '../src/main.js';
import { createHomeView } from '../src/views/home.js';
import { createPhotosView } from '../src/views/photos.js';
import { makeFixtureState } from '../dev/fixtures.js';

const html = readFileSync(resolve(process.cwd(), 'index.html'), 'utf8');
const body = html.match(/<body>([\s\S]*?)<script/)[1];
const SECTIONS = ['home', 'calendar', 'tasks', 'shopping', 'photos', 'control', 'claude'];

describe('slideshow images across the whole document', () => {
  let shell;
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 22, 12, 0));
  });
  afterEach(() => {
    shell?.stop();
    vi.useRealTimers();
    document.body.innerHTML = '';
    document.documentElement.className = '';
    document.documentElement.removeAttribute('data-theme');
  });

  function setup(mode = 'on') {
    document.body.innerHTML = body;
    const state = makeFixtureState(new Date());
    state.screen = { mode };
    const store = createStore({ load: async () => state });
    const views = Object.fromEntries(SECTIONS.map((n) => [n, { mount: vi.fn(), update: vi.fn() }]));
    views.home = createHomeView();
    views.photos = createPhotosView();
    shell = boot({ doc: document, store, api: { act: vi.fn(), getState: async () => state }, views });
    return { store, state };
  }

  const count = () => document.querySelectorAll('img.ss-img').length;

  it('never holds more than two slideshow images while switching views', async () => {
    setup();
    await vi.advanceTimersByTimeAsync(0);
    expect(count()).toBe(2);
    expect(document.querySelectorAll('[data-view="home"] img.ss-img')).toHaveLength(2);
    for (const name of ['photos', 'calendar', 'photos', 'home', 'photos']) {
      shell.router.go(name);
      await vi.advanceTimersByTimeAsync(3000);
      expect(count()).toBeLessThanOrEqual(2);
    }
    expect(document.querySelectorAll('[data-view="photos"] img.ss-img')).toHaveLength(2);
    shell.router.go('calendar');
    expect(count()).toBe(0);
  });

  it('pauses the slideshow while the screen is off and resumes on wake', async () => {
    const { store, state } = setup('off');
    await vi.advanceTimersByTimeAsync(3000);
    const front = () => document.querySelector('[data-view="home"] img.ss-img.is-in');
    const before = front() && front().getAttribute('src');
    await vi.advanceTimersByTimeAsync(60000);
    expect(front() && front().getAttribute('src')).toBe(before);
    store.set({ ...state, screen: { mode: 'on' } });
    await vi.advanceTimersByTimeAsync(15000);
    expect(front()).not.toBeNull();
    expect(front().getAttribute('src')).not.toBe(before);
  });
});
