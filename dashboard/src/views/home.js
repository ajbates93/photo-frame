import '../css/views/home.css';
import { GRID, layoutDay, allDayOn, nextEvent, leaveBy } from '../lib/calendar.js';
import {
  fmtTime, fmtHour, fmtRange, fmtDay, fmtDate, fmtCountdown, dayStart, addDays,
} from '../lib/time.js';
import { photoCaption } from '../lib/captions.js';
import { createSlideshow } from '../ui/slideshow.js';
import { icon } from '../ui/icons.js';

const CLIP = 'white-space:nowrap;overflow:hidden;text-overflow:ellipsis';
const HERO_FAR_MINS = 100;
const MAX_PLUGS = 4;
const COND_ICON = {
  sun: 'sun', partly: 'partly', cloud: 'cloud', rain: 'rain', snow: 'cloud', fog: 'cloud', storm: 'rain', night: 'moon',
};

const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function tint(hex, alpha) {
  const m = /^#([0-9a-f]{6})$/i.exec(hex || '');
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

function setHtml(el, html) {
  if (el.__html === html) return;
  el.__html = html;
  el.innerHTML = html;
}

function hourLines() {
  const span = GRID.endHour - GRID.startHour;
  let out = '';
  for (let h = GRID.startHour + 1; h < GRID.endHour; h += 1) {
    out += `<div class="hl" style="top:${(((h - GRID.startHour) / span) * 100).toFixed(3)}%"></div>`;
    out += `<div class="hl half" style="top:${(((h - 0.5 - GRID.startHour) / span) * 100).toFixed(3)}%"></div>`;
  }
  return out;
}

function gutter() {
  const span = GRID.endHour - GRID.startHour;
  let out = '';
  for (let h = GRID.startHour + 1; h < GRID.endHour; h += 1) {
    out += `<div style="top:${(((h - GRID.startHour) / span) * 100).toFixed(3)}%">${fmtHour(h)}</div>`;
  }
  return out;
}

const SKELETON = `
<div class="home">
  <div class="t clock" data-go="calendar"><div class="time"></div><div class="date"></div></div>
  <div class="t hero" data-go="calendar"></div>
  <div class="side">
    <div class="t photo" data-go="photos"><div class="shade"></div><div class="cap"></div></div>
    <div class="t plugs"></div>
  </div>
  <div class="t weather" data-go="control"></div>
  <div class="t agenda" data-go="calendar">
    <div></div><div class="ag-h today"></div><div class="ag-h"></div>
    <div class="gutter">${gutter()}</div>
    <div class="col">${hourLines()}<div class="items"></div></div>
    <div class="col d2">${hourLines()}<div class="items"></div></div>
  </div>
  <div class="duo">
    <div class="t tasks" data-go="tasks"></div>
    <div class="t shopping" data-go="shopping"></div>
  </div>
  <div class="t claude" data-go="claude"></div>
</div>`;

function heroHtml(state, now) {
  const next = nextEvent(state.events || [], now);
  if (!next) {
    return { cls: 'empty', html: '<div class="main"><div class="lbl">Next up</div><h3 class="clip">Nothing coming up</h3><div class="meta">The next 48 hours are clear</div></div>' };
  }
  const start = new Date(next.start);
  const end = new Date(next.end);
  const cal = (state.calendars || []).find((c) => c.id === next.calendarId);
  const mins = Math.max(0, (start - now) / 60000);
  const count = mins < HERO_FAR_MINS
    ? `${fmtCountdown(mins)}<small>TO GO</small>`
    : `${fmtTime(start)}<small>STARTS</small>`;
  const lb = leaveBy(next);
  const meta = fmtRange(start, end) + (next.location ? ` · ${next.location}` : '');
  return {
    cls: '',
    html: `<div class="main"><div class="lbl">Next up${cal ? ` · ${esc(cal.label)}` : ''}</div>`
      + `<h3 class="clip" style="${CLIP}">${esc(next.title)}</h3>`
      + `<div class="meta clip" style="${CLIP}">${esc(meta)}</div>`
      + (lb ? `<div class="pill">${icon('car', 18)}Leave by ${fmtTime(lb)}</div>` : '')
      + `</div><div class="count">${count}</div>`,
  };
}

function weatherHtml(w) {
  if (!w) return '<div class="lbl">Weather</div><div class="placeholder">Weather unavailable</div>';
  const hours = (w.hourly || []).slice(0, 6).map((h) => `<div>${fmtHour(new Date(h.time).getHours())}`
    + `${icon(COND_ICON[h.cond] || 'cloud', 20)}<b>${Math.round(h.temp)}°</b></div>`).join('');
  return `<div class="lbl">${esc(w.location || 'Weather')}</div>`
    + `<div class="wx-top">${icon(COND_ICON[w.cond] || 'cloud', 40)}<span class="wx-temp">${Math.round(w.temp)}°</span>`
    + `<span class="small" style="margin:0"><b>${esc(w.label)}</b><br>H ${Math.round(w.hi)}° · L ${Math.round(w.lo)}°</span></div>`
    + `<div class="wx-say">${esc(w.summary)}</div><div class="hours">${hours}</div>`;
}

function blockHtml(b, cal) {
  const e = b.event;
  const start = new Date(e.start);
  const end = new Date(e.end);
  const oneLine = b.short || b.clampedStart || b.clampedEnd;
  const color = cal && /^#[0-9a-f]{6}$/i.test(cal.color || '') ? cal.color : null;
  const style = [
    `top:calc(${b.topPct.toFixed(3)}% + 1px)`,
    `height:calc(${b.heightPct.toFixed(3)}% - 3px)`,
    `left:calc(${b.col} / ${b.cols} * 100% + 6px)`,
    `width:calc(100% / ${b.cols} - 14px)`,
    color ? `--ev:${color};--ev-bg:${tint(color, 0.16)}` : '--ev:var(--fam);--ev-bg:var(--fam-bg)',
  ].join(';');
  const cls = `ev${b.past ? ' past' : ''}${oneLine ? ' short' : ''}`;
  // Clamped blocks sit on a grid edge, so label them with their real time.
  const when = (b.clampedStart || b.clampedEnd) ? fmtRange(start, end) : fmtTime(start);
  const inner = oneLine
    ? `<b>${esc(e.title)}</b><span>· ${when}</span>`
    : `<b>${esc(e.title)}</b><span>${fmtRange(start, end)}${e.location ? ` · ${esc(e.location)}` : ''}</span>`;
  return `<div class="${cls}" style="${style}">${inner}</div>`;
}

function dayHtml(events, calendars, day, now, isToday) {
  const calOf = (e) => calendars.find((c) => c.id === e.calendarId);
  const allDay = allDayOn(events, day)
    .map((e) => `<div class="allday">${esc(e.title)}</div>`).join('');
  const blocks = layoutDay(events, day, now).map((b) => blockHtml(b, calOf(b.event))).join('');
  let nowLine = '';
  if (isToday) {
    const h = now.getHours() + now.getMinutes() / 60;
    if (h >= GRID.startHour && h <= GRID.endHour) {
      const pct = ((h - GRID.startHour) / (GRID.endHour - GRID.startHour)) * 100;
      nowLine = `<div class="now" style="top:${pct.toFixed(2)}%"></div>`;
    }
  }
  return (allDay ? `<div class="alldays">${allDay}</div>` : '') + blocks + nowLine;
}

function tasksHtml(tasks) {
  const open = (tasks || []).filter((t) => !t.done);
  const first = open[0];
  return '<div class="lbl">Tasks</div>'
    + `<div class="count-big">${open.length}</div>`
    + `<div class="small clip" style="${CLIP}">${first ? `<b>${esc(first.title)}</b>` : 'All done'}</div>`;
}

function shoppingHtml(shopping) {
  const open = ((shopping && shopping.items) || []).filter((i) => !i.checked);
  const names = open.slice(0, 3).map((i) => i.text).join(', ');
  const more = open.length > 3 ? ` +${open.length - 3}` : '';
  return '<div class="lbl">Shopping</div>'
    + `<div class="count-big">${open.length}</div>`
    + `<div class="small" style="max-height:36px;overflow:hidden">${open.length ? esc(names + more) : 'Nothing needed'}</div>`;
}

function claudeHtml(claude, now) {
  const sessions = (claude && claude.sessions) || [];
  const usage = claude && claude.usage;
  const needs = sessions.some((s) => s.state === 'waiting');
  const head = `<div class="head"><div class="lbl">Claude${usage && usage.plan ? ` · ${esc(usage.plan)} plan` : ''}</div>`
    + `${needs ? '<span class="needs">Needs you</span>' : ''}</div>`;
  if (!usage) return `${head}<div class="placeholder">Usage unavailable</div>`;
  const meter = (label, m, reset) => {
    const pct = Math.max(0, Math.min(100, Math.round(m.pct)));
    return `<div class="meter"><div class="meter-top"><span>${label}</span><b>${pct}% · resets ${reset}</b></div>`
      + `<div class="bar"><i style="width:${pct}%"></i></div></div>`;
  };
  const sessionReset = fmtCountdown(Math.max(0, (new Date(usage.session.resetsAt) - now) / 60000));
  const weeklyReset = fmtDay(new Date(usage.weekly.resetsAt)).slice(0, 3);
  return head + meter('Session', usage.session, sessionReset) + meter('Weekly', usage.weekly, weeklyReset);
}

function plugsHtml(plugs) {
  return (plugs || []).filter((p) => !p.hidden).slice(0, MAX_PLUGS).map((p) => (
    `<button type="button" class="plug${p.on ? ' on' : ''}" data-plug="${esc(p.id)}"${p.reachable ? '' : ' disabled'}>`
    + `${icon('bulb', 22)}<span>${esc(p.name)}</span></button>`)).join('');
}

export function createHomeView() {
  let q = null;
  let ctx = null;
  let state = null;
  let slideshow = null;
  let photoKey = null;
  let current = null;

  const $ = (sel) => q.querySelector(sel);

  function renderCaption() {
    const cap = $('.photo .cap');
    const photo = current;
    const c = photo ? photoCaption(photo.takenAt ? new Date(photo.takenAt) : null, photo.place, ctx.now()) : null;
    setHtml(cap, c ? `<b>${esc(c.kicker || '')}</b>${c.place ? `<span>${esc(c.place)}</span>` : ''}` : '');
  }

  function onClick(e) {
    const plug = e.target.closest('.plug');
    if (plug) {
      e.stopPropagation();
      if (plug.disabled || !state) return;
      const p = (state.plugs || []).find((x) => x.id === plug.dataset.plug);
      if (p) ctx.act('POST', `/api/plugs/${p.id}`, { on: !p.on });
      return;
    }
    if (e.target.closest('.plugs')) return;
    const tile = e.target.closest('[data-go]');
    if (tile) ctx.go(tile.dataset.go);
  }

  return {
    mount(el, c) {
      ctx = c;
      el.innerHTML = SKELETON;
      q = el;
      el.addEventListener('click', onClick);
      slideshow = createSlideshow($('.photo'), {
        onChange: (p) => { current = p; renderCaption(); },
      });
    },

    show(c) {
      if (c) ctx = c;
      slideshow.start();
    },

    hide() {
      slideshow.stop();
    },

    update(s, c) {
      ctx = c;
      state = s;
      const now = c.now();

      const t = fmtTime(now);
      const m = /^(\d+:\d+)(am|pm)$/.exec(t);
      setHtml($('.clock .time'), m ? `${m[1]}<small>${m[2]}</small>` : t);
      setHtml($('.clock .date'), `<b>${fmtDay(now)}</b> ${fmtDate(now)}`);

      const hero = heroHtml(s, now);
      $('.hero').classList.toggle('empty', hero.cls === 'empty');
      setHtml($('.hero'), hero.html);

      setHtml($('.plugs'), plugsHtml(s.plugs));
      setHtml($('.weather'), weatherHtml(s.weather));

      const today = dayStart(now);
      const tomorrow = addDays(today, 1);
      const cols = q.querySelectorAll('.agenda .col');
      const heads = q.querySelectorAll('.ag-h');
      const events = s.events || [];
      const calendars = s.calendars || [];
      [[today, true], [tomorrow, false]].forEach(([day, isToday], i) => {
        setHtml(heads[i], `${isToday ? 'Today' : 'Tomorrow'} <span>${fmtDay(day).slice(0, 3)} ${day.getDate()}</span>`);
        setHtml(cols[i].querySelector('.items'), dayHtml(events, calendars, day, now, isToday));
      });

      setHtml($('.tasks'), tasksHtml(s.tasks));
      setHtml($('.shopping'), shoppingHtml(s.shopping));
      setHtml($('.claude'), claudeHtml(s.claude, now));

      const photos = s.photos || [];
      const key = photos.map((p) => p.id).join(',');
      if (key !== photoKey) {
        photoKey = key;
        slideshow.setPhotos(photos);
      }
    },
  };
}
