import '../css/views/calendar.css';
import { fmtRange, fmtDay, fmtDate, dayStart, addDays } from '../lib/time.js';
import { esc, setHtml, validColor } from '../ui/html.js';
import { gutterHtml, hourLinesHtml, dayItemsHtml } from '../ui/agenda.js';

const DAYS = 5;
// /api/state carries events from the start of today to today + 14 days.
const WINDOW_DAYS = 14;

const shortDate = (d) => `${d.getDate()} ${fmtDate(d).split(' ')[1].slice(0, 3)}`;

function dot(color) {
  const c = validColor(color);
  return `<i class="dot" style="background:${c || 'var(--fam)'}"></i>`;
}

function columns() {
  let out = '<div class="gutter">' + gutterHtml() + '</div>';
  for (let i = 0; i < DAYS; i += 1) {
    out += `<div class="col${i ? ' d2' : ''}">${hourLinesHtml()}<div class="items"></div></div>`;
  }
  return out;
}

const SKELETON = `
<div class="cal">
  <div class="cal-bar">
    <div class="cal-nav">
      <button type="button" class="cal-btn" data-page="prev" aria-label="Previous five days">&#8249;</button>
      <button type="button" class="cal-btn cal-today" data-page="today">Today</button>
      <button type="button" class="cal-btn" data-page="next" aria-label="Next five days">&#8250;</button>
    </div>
    <div class="cal-range"></div>
    <div class="cal-legend"></div>
  </div>
  <div class="cal-grid">
    <div></div>
    ${'<div class="ag-h"></div>'.repeat(DAYS)}
    ${columns()}
  </div>
  <div class="sheet" hidden>
    <div class="sheet-back"></div>
    <div class="sheet-card" role="dialog" aria-modal="true">
      <div class="sheet-body"></div>
      <button type="button" class="cal-btn sheet-close">Close</button>
    </div>
  </div>
</div>`;

export function createCalendarView() {
  let q = null;
  let ctx = null;
  let state = null;
  let offset = 0; // days from today to the first column

  const $ = (sel) => q.querySelector(sel);

  function closeSheet() { $('.sheet').hidden = true; }

  function openSheet(id) {
    const e = ((state && state.events) || []).find((x) => x.id === id);
    if (!e) return;
    const cal = ((state && state.calendars) || []).find((c) => c.id === e.calendarId);
    const when = e.allDay ? 'All day' : fmtRange(new Date(e.start), new Date(e.end));
    setHtml($('.sheet-body'),
      `<h3>${esc(e.title)}</h3><div class="sheet-when">${esc(when)}</div>`
      + (e.location ? `<div class="sheet-loc">${esc(e.location)}</div>` : '')
      + (cal ? `<div class="sheet-cal">${dot(cal.color)}${esc(cal.label)}</div>` : ''));
    $('.sheet').hidden = false;
  }

  function render() {
    if (!state || !q) return;
    const now = ctx.now();
    const today = dayStart(now);
    const events = state.events || [];
    const calendars = state.calendars || [];
    const heads = q.querySelectorAll('.ag-h');
    const items = q.querySelectorAll('.col .items');
    const first = addDays(today, offset);
    const last = addDays(first, DAYS - 1);
    for (let i = 0; i < DAYS; i += 1) {
      const day = addDays(first, i);
      const diff = offset + i;
      const label = diff === 0 ? 'Today' : diff === 1 ? 'Tomorrow' : fmtDay(day);
      heads[i].classList.toggle('today', diff === 0);
      setHtml(heads[i], `${label} <span>${shortDate(day)}</span>`);
      setHtml(items[i], dayItemsHtml(events, calendars, day, now, diff === 0));
    }
    setHtml($('.cal-range'), `${shortDate(first)} – ${shortDate(last)}`);
    q.querySelector('.cal-today').disabled = offset === 0;
    q.querySelector('[data-page="prev"]').disabled = offset === 0;
    q.querySelector('[data-page="next"]').disabled = offset + DAYS > WINDOW_DAYS;
    setHtml($('.cal-legend'), calendars.map((c) => `<span>${dot(c.color)}${esc(c.label)}</span>`).join(''));
  }

  function onClick(e) {
    const t = e.target;
    if (t.closest('.sheet-close') || t.closest('.sheet-back')) { closeSheet(); return; }
    const page = t.closest('[data-page]');
    if (page) {
      const k = page.dataset.page;
      if (page.disabled) return;
      const to = k === 'today' ? 0 : offset + (k === 'next' ? DAYS : -DAYS);
      offset = Math.max(0, Math.min(to, Math.floor(WINDOW_DAYS / DAYS) * DAYS));
      render();
      return;
    }
    const ev = t.closest('[data-eid]');
    if (ev) openSheet(ev.dataset.eid);
  }

  return {
    mount(el, c) {
      ctx = c;
      el.innerHTML = SKELETON;
      q = el;
      el.addEventListener('click', onClick);
    },

    show(c) {
      if (c) ctx = c;
      offset = 0;
      closeSheet();
      render();
    },

    hide() { closeSheet(); },

    update(s, c) {
      ctx = c;
      state = s;
      render();
    },
  };
}
