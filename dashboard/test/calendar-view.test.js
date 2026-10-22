import { makeFixtureState } from '../dev/fixtures.js';
import { createCalendarView } from '../src/views/calendar.js';

const NOW = new Date(2026, 9, 22, 8, 42);

function setup(tweak) {
  const state = makeFixtureState(NOW);
  if (tweak) tweak(state);
  const el = document.createElement('section');
  document.body.appendChild(el);
  const ctx = { now: () => NOW, act: vi.fn(async () => {}), go: vi.fn(), toast: vi.fn() };
  const view = createCalendarView();
  view.mount(el, ctx);
  view.update(state, ctx);
  return { el, ctx, view, state };
}

const heads = (el) => [...el.querySelectorAll('.ag-h')].map((h) => h.textContent);

describe('calendar view', () => {
  afterEach(() => { document.body.innerHTML = ''; });

  it('renders five day columns headed Today, Tomorrow, then weekdays', () => {
    const { el } = setup();
    expect(el.querySelectorAll('.col')).toHaveLength(5);
    const h = heads(el);
    expect(h[0]).toContain('Today');
    expect(h[1]).toContain('Tomorrow');
    expect(h[2]).toContain('Saturday');
    expect(h[2]).toContain('24 Oct');
    expect(h[4]).toContain('Monday');
  });

  it('puts a now line only in today', () => {
    const { el } = setup();
    expect(el.querySelectorAll('.now')).toHaveLength(1);
    expect(el.querySelectorAll('.col')[0].contains(el.querySelector('.now'))).toBe(true);
  });

  it('renders the overlapping pair side by side at 50%', () => {
    const { el } = setup();
    const swim = [...el.querySelectorAll('.ev')].find((e) => e.textContent.includes('Swimming'));
    const parents = [...el.querySelectorAll('.ev')].find((e) => e.textContent.includes("Parents"));
    expect(swim.style.width).toContain('50%');
    expect(parents.style.width).toContain('50%');
  });

  it('legend lists both calendars', () => {
    const { el } = setup();
    const t = el.querySelector('.cal-legend').textContent;
    expect(t).toContain('Alex');
    expect(t).toContain('Family');
  });

  it('next and previous page by five days, Today returns', () => {
    const { el } = setup();
    el.querySelector('[data-page="next"]').click();
    expect(heads(el)[0]).toContain('27 Oct');
    expect(heads(el)[0]).not.toContain('Today');
    el.querySelector('[data-page="next"]').click();
    expect(heads(el)[0]).toContain('1 Nov');
    el.querySelector('[data-page="prev"]').click();
    expect(heads(el)[0]).toContain('27 Oct');
    el.querySelector('[data-page="today"]').click();
    expect(heads(el)[0]).toContain('Today');
    expect(el.querySelectorAll('.now')).toHaveLength(1);
  });

  it('tapping an event opens a sheet with details, and it closes', () => {
    const { el } = setup();
    const ev = [...el.querySelectorAll('.ev')].find((e) => e.textContent.includes('Swimming'));
    ev.click();
    const sheet = el.querySelector('.sheet');
    expect(sheet.hidden).toBe(false);
    expect(sheet.textContent).toContain('Swimming lessons');
    expect(sheet.textContent).toContain('5:30pm–6:15pm');
    el.querySelector('.sheet-close').click();
    expect(el.querySelector('.sheet').hidden).toBe(true);
    ev.click();
    el.querySelector('.sheet-back').click();
    expect(el.querySelector('.sheet').hidden).toBe(true);
  });

  it('escapes event text and ignores bad calendar colours', () => {
    const { el } = setup((s) => {
      s.calendars[0].color = 'red;background:url(x)';
      s.calendars[0].label = '<i>Al</i>';
      s.events[1].title = '<img src=x>';
      s.events[1].calendarId = s.calendars[0].id;
    });
    expect(el.querySelector('img')).toBeNull();
    expect(el.querySelectorAll('.cal-legend i')).toHaveLength(2); // dots only, no injected tag
    expect(el.querySelector('.cal-legend .dot').getAttribute('style')).toBe('background:var(--fam)');
    expect(el.innerHTML).not.toContain('url(x)');
  });
});
