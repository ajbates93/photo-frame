import { makeFixtureState } from '../dev/fixtures.js';
import { createHomeView } from '../src/views/home.js';

const NOW = new Date(2026, 9, 22, 8, 42);

function setup(now = NOW, tweak) {
  const state = makeFixtureState(now);
  if (tweak) tweak(state);
  const el = document.createElement('section');
  document.body.appendChild(el);
  const ctx = { now: () => now, act: vi.fn(async () => {}), go: vi.fn(), toast: vi.fn() };
  const view = createHomeView();
  view.mount(el, ctx);
  view.update(state, ctx);
  return { el, ctx, view, state };
}

describe('home view', () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); document.body.innerHTML = ''; });

  it('weather tile is inert: no data-go, and clicking it does not navigate', () => {
    const { el, ctx } = setup();
    const tile = el.querySelector('.weather');
    expect(tile.hasAttribute('data-go')).toBe(false);
    tile.click();
    el.querySelector('.weather .lbl').click();
    expect(ctx.go).not.toHaveBeenCalled();
  });

  it('hero shows the next event, and leave-by when travel is set', () => {
    let s = setup();
    expect(s.el.querySelector('.hero h3').textContent).toBe('Stand-up');
    expect(s.el.querySelector('.hero .pill')).toBeNull();
    expect(s.el.querySelector('.hero .count').textContent).toContain('18 min');
    s = setup(new Date(2026, 9, 22, 17, 0));
    expect(s.el.querySelector('.hero h3').textContent).toBe('Swimming lessons');
    expect(s.el.querySelector('.hero .pill').textContent).toContain('Leave by 5:10pm');
  });

  it('hero names the day when the next event is not today', () => {
    const { el } = setup(new Date(2026, 9, 22, 20, 15));
    expect(el.querySelector('.hero h3').textContent).toBe('Design review');
    expect(el.querySelector('.hero .meta').textContent).toBe('Tomorrow · 10:00am–11:00am · Office');
    const later = setup(new Date(2026, 9, 22, 20, 15), (st) => {
      st.events = [{ ...st.events.find((e) => e.title === 'Stand-up'), start: new Date(2026, 9, 24, 9).toISOString(), end: new Date(2026, 9, 24, 10).toISOString() }];
    });
    expect(later.el.querySelector('.hero .meta').textContent).toBe('Saturday · 9:00am–10:00am');
    const today = setup();
    expect(today.el.querySelector('.hero .meta').textContent).toBe('9:00am–9:30am');
  });

  it('weather shows hourly entries from the current hour onward', () => {
    const { el } = setup(new Date(2026, 9, 22, 14, 30), (st) => {
      st.weather.hourly = [10, 12, 14, 16, 18, 20].map((h) => ({
        time: new Date(2026, 9, 22, h).toISOString(), temp: 10, cond: 'cloud', rainPct: 0,
      }));
    });
    const hours = [...el.querySelectorAll('.weather .hours > div')].map((d) => d.textContent);
    expect(hours.map((h) => h.match(/^\d+(am|pm)/)[0])).toEqual(['2pm', '4pm', '6pm', '8pm']);
  });

  it('hero says nothing coming up when there are no events in 48 h', () => {
    const { el } = setup(NOW, (st) => { st.events = []; });
    expect(el.querySelector('.hero').textContent).toContain('Nothing coming up');
  });

  it('hero shows the start time when the event is far off', () => {
    const { el } = setup(new Date(2026, 9, 22, 9, 40));
    expect(el.querySelector('.hero h3').textContent).toBe('Client call');
    expect(el.querySelector('.hero .count').textContent).toContain('11:30am');
  });

  it('agenda has 12 hour lines per day and a now line at the right height', () => {
    const { el } = setup();
    const cols = el.querySelectorAll('.agenda .col');
    expect(cols).toHaveLength(2);
    cols.forEach((c) => expect(c.querySelectorAll('.hl:not(.half)')).toHaveLength(12));
    const now = el.querySelectorAll('.agenda .now');
    expect(now).toHaveLength(1);
    expect(parseFloat(now[0].style.top)).toBeCloseTo(5.38, 1);
    expect(cols[0].contains(now[0])).toBe(true);
  });

  it('agenda marks past and short events and shows all-day events', () => {
    const { el } = setup(new Date(2026, 9, 22, 10, 0));
    const evs = [...el.querySelectorAll('.agenda .col')[0].querySelectorAll('.ev')];
    const standup = evs.find((e) => e.textContent.includes('Stand-up'));
    expect(standup.classList.contains('past')).toBe(true);
    expect(standup.classList.contains('short')).toBe(true);
    expect(el.querySelectorAll('.agenda .col')[1].querySelector('.allday').textContent).toContain('Vicky away');
  });

  it('shows both pre-08:00 fixture events side by side at the top edge', () => {
    const { el } = setup();
    const evs = [...el.querySelectorAll('.agenda .col')[0].querySelectorAll('.ev')];
    const early = ['Gym', 'Dog walk'].map((t) => evs.find((e) => e.textContent.includes(t)));
    early.forEach((e) => {
      expect(e.style.top).toMatch(/^calc\(0(\.0+)?% \+ 1px\)$/);
      expect(e.style.width).toContain('50%');
    });
    expect(early[0].style.left).not.toBe(early[1].style.left);
    // Edge blocks are only 3% tall: they stay one line (not the 2-line side-by-side wrap).
    early.forEach((e) => expect(e.classList.contains('edge')).toBe(true));
    const swim = evs.find((e) => e.textContent.includes('Swimming'));
    expect(swim.classList.contains('edge')).toBe(false);
  });

  it('gives overlapping events side-by-side columns', () => {
    const { el } = setup();
    const swim = [...el.querySelectorAll('.ev')].find((e) => e.textContent.includes('Swimming'));
    expect(swim.style.width).toContain('50%');
  });

  it('claude tile shows Needs you only while a session is waiting', () => {
    const a = setup();
    expect(a.el.querySelector('.claude').textContent).toContain('Needs you');
    const b = setup(NOW, (st) => { st.claude.sessions.forEach((x) => { x.state = 'working'; }); });
    expect(b.el.querySelector('.claude .needs')).toBeNull();
  });

  it('renders placeholders for null weather and usage', () => {
    const { el } = setup(NOW, (st) => {
      st.weather = null; st.claude.usage = null; st.photos = []; st.speaker = null;
    });
    expect(el.querySelector('.weather').textContent).toContain('Weather unavailable');
    expect(el.querySelector('.claude').textContent).toContain('Usage unavailable');
  });

  it('treats usage without a session or weekly meter as unavailable', () => {
    for (const usage of [
      { plan: 'Max', session: null, weekly: { pct: 61, resetsAt: NOW.toISOString() } },
      { plan: 'Max', session: { pct: 42, resetsAt: NOW.toISOString() } },
      { plan: 'Max', session: { pct: 'x', resetsAt: NOW.toISOString() }, weekly: { pct: 61, resetsAt: NOW.toISOString() } },
      { plan: 'Max', session: { pct: 42, resetsAt: 'soon' }, weekly: { pct: 61, resetsAt: NOW.toISOString() } },
    ]) {
      const { el } = setup(NOW, (st) => { st.claude.usage = usage; });
      expect(el.querySelector('.claude').textContent).toContain('Usage unavailable');
      expect(el.querySelector('.claude').textContent).not.toContain('NaN');
      document.body.innerHTML = '';
    }
  });

  it('truncates long titles with an ellipsis', () => {
    const long = 'A'.repeat(60);
    const { el } = setup(NOW, (st) => { st.events.find((e) => e.title === 'Stand-up').title = long; });
    expect(el.querySelector('.hero h3').style.textOverflow).toBe('ellipsis');
  });

  it('plug buttons toggle via the API and do not navigate; tiles navigate', () => {
    const { el, ctx } = setup();
    el.querySelector('.plug').click();
    expect(ctx.act).toHaveBeenCalledWith('POST', '/api/plugs/pl1', { on: false });
    expect(ctx.go).not.toHaveBeenCalled();
    el.querySelector('.hero').click();
    expect(ctx.go).toHaveBeenCalledWith('calendar');
    el.querySelector('.claude').click();
    expect(ctx.go).toHaveBeenCalledWith('claude');
  });

  it('asks before turning a confirm plug off from the home strip, like Control', () => {
    const { el, ctx } = setup(NOW, (st) => { st.plugs[0].confirm = true; st.plugs[0].name = '<b>Lamp</b>'; });
    el.querySelector('.plug[data-plug="pl1"]').click();
    expect(ctx.act).not.toHaveBeenCalled();
    const sheet = el.querySelector('.sheet');
    expect(sheet.hidden).toBe(false);
    expect(sheet.querySelector('.confirm-title').textContent).toBe('Turn off <b>Lamp</b>?');
    sheet.querySelector('.sheet-close').click();
    expect(sheet.hidden).toBe(true);
    expect(ctx.act).not.toHaveBeenCalled();
    expect(ctx.go).not.toHaveBeenCalled();
    el.querySelector('.plug[data-plug="pl1"]').click();
    sheet.querySelector('[data-confirm]').click();
    expect(ctx.act).toHaveBeenCalledWith('POST', '/api/plugs/pl1', { on: false });
    expect(sheet.hidden).toBe(true);
    expect(ctx.go).not.toHaveBeenCalled();
  });

  it('turns a confirm plug on without asking, and closes the sheet on hide', () => {
    const { el, ctx, view } = setup(NOW, (st) => { st.plugs.forEach((p) => { p.confirm = true; }); });
    el.querySelector('.plug[data-plug="pl2"]').click();
    expect(ctx.act).toHaveBeenCalledWith('POST', '/api/plugs/pl2', { on: true });
    el.querySelector('.plug[data-plug="pl1"]').click();
    expect(el.querySelector('.sheet').hidden).toBe(false);
    view.hide();
    expect(el.querySelector('.sheet').hidden).toBe(true);
  });

  it('encodes the plug id in the API path', () => {
    const { el, ctx } = setup(NOW, (st) => { st.plugs[0].id = 'a/b c'; });
    el.querySelector('.plug').click();
    expect(ctx.act).toHaveBeenCalledWith('POST', '/api/plugs/a%2Fb%20c', { on: false });
  });

  it('skips hidden plugs and keeps unreachable ones inert', () => {
    const { el, ctx } = setup(NOW, (st) => {
      st.plugs[0].hidden = true; st.plugs[1].reachable = false;
    });
    const plugs = [...el.querySelectorAll('.plug')];
    expect(plugs).toHaveLength(3);
    const dead = plugs.find((p) => p.textContent.includes('Reading lamp'));
    expect(dead.disabled).toBe(true);
    dead.click();
    expect(ctx.act).not.toHaveBeenCalled();
  });

  it('only keeps two slideshow images and rebuilds nothing on repeat updates', () => {
    const { el, view, ctx, state } = setup();
    view.show(ctx);
    expect(el.querySelectorAll('.photo img')).toHaveLength(2);
    const first = el.querySelector('.photo img');
    view.update(state, ctx);
    view.update(state, ctx);
    expect(el.querySelector('.photo img')).toBe(first);
    expect(el.querySelectorAll('.photo img').length).toBeLessThanOrEqual(2);
  });

  it('puts the slideshow images under the caption shade', () => {
    const { el, view, ctx } = setup();
    view.show(ctx);
    const photo = el.querySelector('.photo');
    const kids = [...photo.children];
    expect(kids.filter((k) => k.tagName === 'IMG')).toHaveLength(2);
    const shade = kids.indexOf(photo.querySelector('.shade'));
    kids.filter((k) => k.tagName === 'IMG').forEach((im) => expect(kids.indexOf(im)).toBeLessThan(shade));
  });

  it('ignores a malicious calendar colour', () => {
    const { el } = setup(NOW, (st) => { st.calendars[0].color = 'red;"><b id="x">'; });
    expect(el.querySelector('#x')).toBeNull();
    const ev = [...el.querySelectorAll('.ev')].find((e) => e.textContent.includes('Stand-up'));
    expect(ev.getAttribute('style')).toContain('var(--fam)');
  });

  it('stops the slideshow timers on hide and restarts on show', () => {
    const { view, ctx } = setup();
    expect(vi.getTimerCount()).toBe(0);
    view.show(ctx);
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    view.hide();
    expect(vi.getTimerCount()).toBe(0);
    view.show(ctx);
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    view.hide();
  });
});

describe('home view offline (no state yet)', () => {
  afterEach(() => { document.body.innerHTML = ''; });

  it('keeps the clock and shows a placeholder in every tile', () => {
    const el = document.createElement('section');
    document.body.appendChild(el);
    const ctx = { now: () => NOW, act: vi.fn(), go: vi.fn(), toast: vi.fn() };
    const view = createHomeView();
    view.mount(el, ctx);
    view.offline(ctx);
    expect(el.querySelector('.clock .time').textContent).toContain('8:42');
    expect(el.querySelector('.hero').textContent).toContain("Can't reach the home server");
    expect(el.querySelector('.weather').textContent).toContain('Weather unavailable');
    expect(el.querySelector('.agenda .unavailable').textContent).toBe('Calendar unavailable');
    expect(el.querySelector('.claude').textContent).toContain('Usage unavailable');
    expect(el.querySelector('.tasks .count-big').textContent).toBe('—');
    expect(el.querySelector('.shopping .count-big').textContent).toBe('—');
  });
});

describe('agenda overlapping blocks', () => {
  afterEach(() => { document.body.innerHTML = ''; });

  it('gives side-by-side blocks the wrapping class and no time line; single blocks are unchanged', () => {
    const { el } = setup(new Date(2026, 9, 22, 17, 0));
    const evs = [...el.querySelectorAll('.agenda .col')[0].querySelectorAll('.ev')];
    const multi = evs.filter((e) => e.classList.contains('multi'));
    expect(multi.length).toBeGreaterThanOrEqual(2);
    multi.forEach((e) => expect(e.querySelector('span')).toBeNull());
    const single = evs.filter((e) => !e.classList.contains('multi'));
    expect(single.length).toBeGreaterThan(0);
    single.forEach((e) => expect(e.querySelector('span')).not.toBeNull());
  });
});
