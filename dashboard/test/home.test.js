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

  it('hero shows the next event, and leave-by when travel is set', () => {
    let s = setup();
    expect(s.el.querySelector('.hero h3').textContent).toBe('Stand-up');
    expect(s.el.querySelector('.hero .pill')).toBeNull();
    expect(s.el.querySelector('.hero .count').textContent).toContain('18 min');
    s = setup(new Date(2026, 9, 22, 17, 0));
    expect(s.el.querySelector('.hero h3').textContent).toBe('Swimming lessons');
    expect(s.el.querySelector('.hero .pill').textContent).toContain('Leave by 5:10pm');
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

  it('truncates long titles with an ellipsis', () => {
    const long = 'A'.repeat(60);
    const { el } = setup(NOW, (st) => { st.events[1].title = long; });
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
    expect(el.querySelectorAll('.photo img').length).toBeLessThanOrEqual(2);
    const first = el.querySelector('.photo img');
    view.update(state, ctx);
    view.update(state, ctx);
    expect(el.querySelector('.photo img')).toBe(first);
    expect(el.querySelectorAll('.photo img').length).toBeLessThanOrEqual(2);
  });
});
