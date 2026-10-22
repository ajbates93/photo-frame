import '@fontsource/instrument-serif/latin-400.css';
import '@fontsource-variable/archivo/wght.css';
import './css/tokens.css';
import './css/base.css';
import { createStore } from './store.js';
import { api as realApi } from './api.js';
import { createRouter } from './router.js';
import { themeFor, nextBoundary } from './lib/theme.js';
import { fmtTime } from './lib/time.js';
import { showUnavailable, clearUnavailable } from './ui/unavailable.js';
import { icon } from './ui/icons.js';
import { createHomeView } from './views/home.js';
import { createCalendarView } from './views/calendar.js';
import { createTasksView } from './views/tasks.js';
import { createShoppingView } from './views/shopping.js';
import { createPhotosView } from './views/photos.js';
import { createControlView } from './views/control.js';
import { createClaudeView } from './views/claude.js';

export const SECTIONS = ['home', 'calendar', 'tasks', 'shopping', 'photos', 'control', 'claude'];
const TITLES = {
  home: 'Home', calendar: 'Calendar', tasks: 'Tasks', shopping: 'Shopping',
  photos: 'Photos', control: 'Control', claude: 'Claude',
};
const TICK_MS = 30000;
const IDLE_MS = 120000;
const TOAST_MS = 3000;
const FADE_MS = 3000;

// Stand-in for the real views of Tasks 6-9: renders the section title only.
export function placeholderView(name) {
  return {
    mount(el) {
      el.innerHTML = '';
      const h = document.createElement('h2');
      h.className = 'placeholder-title';
      h.textContent = TITLES[name] || name;
      el.appendChild(h);
    },
    update() {},
  };
}

// Today's sunrise/sunset as Dates on `now`'s day (the feed may carry another day's times).
function sunTimes(state, now) {
  const w = state && state.weather;
  const pick = (s) => {
    const d = s ? new Date(s) : null;
    if (!d || Number.isNaN(d.getTime())) return null;
    return new Date(now.getFullYear(), now.getMonth(), now.getDate(), d.getHours(), d.getMinutes(), 0, 0);
  };
  return { sunrise: w ? pick(w.sunrise) : null, sunset: w ? pick(w.sunset) : null };
}

export function boot({
  doc = document,
  store = null,
  api = realApi,
  now = () => new Date(),
  views = null,
  forcedTheme = null,
  initialView = 'home',
  stateSearch = '',
} = {}) {
  const html = doc.documentElement;
  const theStore = store || createStore({ load: () => api.getState(stateSearch) });
  const viewMap = views || {
    ...Object.fromEntries(SECTIONS.map((n) => [n, placeholderView(n)])),
    home: createHomeView(),
    calendar: createCalendarView(),
    tasks: createTasksView(),
    shopping: createShoppingView(),
    photos: createPhotosView(),
    control: createControlView(),
    claude: createClaudeView(),
  };
  const overlay = doc.getElementById('overlay');
  const toasts = doc.getElementById('toasts');
  const stalePill = doc.getElementById('stale');
  const railClock = doc.getElementById('railClock');
  let override = null; // { theme, until: Date }
  let appliedTheme = null;
  let fadeTimer = null;
  let idleTimer = null;
  let lastOk = null;
  let waking = false;
  const toastTimers = new Set();
  const life = new AbortController();
  const on = { capture: true, signal: life.signal };

  doc.querySelectorAll('[data-icon]').forEach((el) => { el.innerHTML = icon(el.dataset.icon); });

  function toast(msg) {
    const t = doc.createElement('div');
    t.className = 'toast';
    t.textContent = msg;
    toasts.appendChild(t);
    const id = setTimeout(() => { toastTimers.delete(id); t.remove(); }, TOAST_MS);
    toastTimers.add(id);
  }

  function snapshot() {
    return theStore.get();
  }

  async function act(method, path, body) {
    try {
      const next = await api.act(method, path, body);
      theStore.set(next);
      return true;
    } catch (e) {
      toast((e && e.message) || 'Something went wrong');
      return false;
    }
  }

  const router = createRouter(doc, viewMap, { ctx: () => ctx });
  const ctx = { now, act, go: (name) => go(name), toast };

  function go(name) {
    router.go(name);
    resetIdle();
  }

  function resetIdle() {
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      if (router.current() !== 'home') router.go('home');
    }, IDLE_MS);
  }

  function currentTheme() {
    const t = now();
    if (forcedTheme) return forcedTheme;
    if (override && t >= override.until) override = null;
    if (override) return override.theme;
    const { sunrise, sunset } = sunTimes(snapshot().state, t);
    return themeFor(t, sunrise, sunset);
  }

  function applyTheme() {
    const theme = currentTheme();
    if (theme === appliedTheme) return;
    const first = appliedTheme === null;
    appliedTheme = theme;
    html.dataset.theme = theme;
    if (!first) {
      html.classList.add('theme-fading');
      clearTimeout(fadeTimer);
      fadeTimer = setTimeout(() => html.classList.remove('theme-fading'), FADE_MS);
    }
  }

  railClock.addEventListener('click', () => {
    const t = now();
    const { sunrise, sunset } = sunTimes(snapshot().state, t);
    override = {
      theme: appliedTheme === 'paper' ? 'night' : 'paper',
      until: nextBoundary(t, sunrise, sunset),
    };
    applyTheme();
  });

  function renderOverlay(state) {
    const mode = state && state.screen ? state.screen.mode : 'on';
    overlay.classList.toggle('is-dim', mode === 'dim');
    overlay.classList.toggle('is-off', mode === 'off');
  }

  function renderStale(snap) {
    if (!snap.stale) {
      stalePill.classList.remove('is-visible');
      stalePill.textContent = '';
      return;
    }
    let when = snap.state ? new Date(snap.state.generatedAt) : null;
    if (!when || Number.isNaN(when.getTime())) when = lastOk;
    stalePill.textContent = when ? `Offline · last updated ${fmtTime(when)}` : 'Offline';
    stalePill.classList.add('is-visible');
  }

  function render() {
    const snap = snapshot();
    if (!snap.stale && snap.state) lastOk = now();
    railClock.textContent = fmtTime(now());
    applyTheme();
    renderOverlay(snap.state);
    renderStale(snap);
    if (snap.state) {
      clearUnavailable(doc);
      Object.values(viewMap).forEach((v) => v.update(snap.state, ctx));
    } else if (snap.error) {
      Object.entries(viewMap).forEach(([name, v]) => {
        if (v.offline) { v.offline(ctx); return; }
        const el = doc.querySelector(`[data-view="${name}"]`);
        if (el) showUnavailable(el);
      });
    }
  }

  // Off overlay: it covers the screen, so the next tap lands on it, wakes the frame
  // and never reaches the control underneath. Touch/mouse/pointer events are not cancelled.
  function wake(e) {
    if (!overlay.classList.contains('is-off')) return;
    if (e.type === 'click') e.stopPropagation();
    if (waking) return;
    waking = true;
    act('POST', '/api/screen/wake').finally(() => { waking = false; });
  }
  overlay.addEventListener('pointerup', wake, { signal: life.signal });
  overlay.addEventListener('click', wake, { signal: life.signal });

  // Rail navigation and idle return.
  doc.querySelectorAll('[data-go]').forEach((el) => {
    el.addEventListener('click', () => go(el.dataset.go));
  });
  ['pointerdown', 'touchstart', 'click'].forEach((type) => {
    doc.addEventListener(type, resetIdle, on);
  });

  Object.entries(viewMap).forEach(([name, v]) => {
    const el = doc.querySelector(`[data-view="${name}"]`);
    if (el) v.mount(el, ctx);
  });

  const unsubscribe = theStore.subscribe(render);
  const tick = setInterval(render, TICK_MS);
  go(SECTIONS.includes(initialView) ? initialView : 'home');
  applyTheme();
  render();
  theStore.refresh();

  return { router, ctx, store: theStore, stop() {
      life.abort();
      unsubscribe();
      clearInterval(tick);
      clearTimeout(idleTimer);
      clearTimeout(fadeTimer);
      toastTimers.forEach(clearTimeout);
      toastTimers.clear();
    } };
}

// Dev-only page flags: ?theme, ?view, ?now (pins the clock), ?nulls and ?fail (forwarded to the mock API).
export function devFlags(search = '') {
  const q = new URLSearchParams(search);
  const theme = q.get('theme');
  const view = q.get('view');
  const nowRaw = q.get('now');
  const nowDate = nowRaw ? new Date(nowRaw) : null;
  const pinned = nowDate && !Number.isNaN(nowDate.getTime()) ? nowDate : null;
  const fwd = new URLSearchParams();
  if (q.get('nulls') === '1') fwd.set('nulls', '1');
  if (q.get('fail') === '1') fwd.set('fail', '1');
  if (pinned) fwd.set('now', nowRaw);
  const str = fwd.toString();
  return {
    forcedTheme: theme === 'paper' || theme === 'night' ? theme : null,
    initialView: SECTIONS.includes(view) ? view : 'home',
    now: pinned,
    stateSearch: str ? `?${str}` : '',
  };
}

if (import.meta.env.MODE !== 'test') {
  const opts = {};
  if (import.meta.env.DEV) {
    const { now: pinned, ...rest } = devFlags(location.search);
    Object.assign(opts, rest);
    if (pinned) opts.now = () => new Date(pinned.getTime());
  }
  boot(opts);
}
