import '../css/views/home.css';
import { nextEvent, leaveBy } from '../lib/calendar.js';
import {
  fmtTime, fmtHour, fmtRange, fmtDay, fmtDate, fmtCountdown, dayStart, addDays,
} from '../lib/time.js';
import { photoCaption } from '../lib/captions.js';
import { usableUsage } from '../lib/usage.js';
import { createSlideshow } from '../ui/slideshow.js';
import { createPlugToggle } from '../ui/plug-toggle.js';
import { icon } from '../ui/icons.js';
import { esc, setHtml } from '../ui/html.js';
import { showUnavailable, OFFLINE_MESSAGE } from '../ui/unavailable.js';
import { gutterHtml, hourLinesHtml, dayItemsHtml } from '../ui/agenda.js';

const CLIP = 'white-space:nowrap;overflow:hidden;text-overflow:ellipsis';
const HERO_FAR_MINS = 100;
const MAX_PLUGS = 4;
const COND_ICON = {
  sun: 'sun', partly: 'partly', cloud: 'cloud', rain: 'rain', snow: 'cloud', fog: 'cloud', storm: 'rain', night: 'moon',
};

const SKELETON = `
<div class="home">
  <div class="t clock" data-go="calendar"><div class="time"></div><div class="date"></div></div>
  <div class="t hero" data-go="calendar"></div>
  <div class="side">
    <div class="t photo" data-go="photos"><div class="shade"></div><div class="cap"></div></div>
    <div class="t plugs"></div>
  </div>
  <div class="t weather"></div>
  <div class="t agenda" data-go="calendar">
    <div></div><div class="ag-h today"></div><div class="ag-h"></div>
    <div class="gutter">${gutterHtml()}</div>
    <div class="col">${hourLinesHtml()}<div class="items"></div></div>
    <div class="col d2">${hourLinesHtml()}<div class="items"></div></div>
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
  // The next event can be up to 48 h away: name its day unless it is today.
  const days = Math.round((dayStart(start) - dayStart(now)) / 86400000);
  const day = days === 0 ? '' : `${days === 1 ? 'Tomorrow' : fmtDay(start)} · `;
  const meta = day + fmtRange(start, end) + (next.location ? ` · ${next.location}` : '');
  return {
    cls: '',
    html: `<div class="main"><div class="lbl">Next up${cal ? ` · ${esc(cal.label)}` : ''}</div>`
      + `<h3 class="clip" style="${CLIP}">${esc(next.title)}</h3>`
      + `<div class="meta clip" style="${CLIP}">${esc(meta)}</div>`
      + (lb ? `<div class="pill">${icon('car', 18)}Leave by ${fmtTime(lb)}</div>` : '')
      + `</div><div class="count">${count}</div>`,
  };
}

function weatherHtml(w, now) {
  if (!w) return '<div class="lbl">Weather</div><div class="placeholder">Weather unavailable</div>';
  // Entries before the current hour are dropped (the server should not send them).
  const hourStart = new Date(now.getFullYear(), now.getMonth(), now.getDate(), now.getHours()).getTime();
  const hours = (w.hourly || []).filter((h) => new Date(h.time).getTime() >= hourStart).slice(0, 6).map((h) => `<div>${fmtHour(new Date(h.time).getHours())}`
    + `${icon(COND_ICON[h.cond] || 'cloud', 20)}<b>${Math.round(h.temp)}°</b></div>`).join('');
  return `<div class="lbl">${esc(w.location || 'Weather')}</div>`
    + `<div class="wx-top">${icon(COND_ICON[w.cond] || 'cloud', 40)}<span class="wx-temp">${Math.round(w.temp)}°</span>`
    + `<span class="small" style="margin:0"><b>${esc(w.label)}</b><br>H ${Math.round(w.hi)}° · L ${Math.round(w.lo)}°</span></div>`
    + `<div class="wx-say">${esc(w.summary)}</div><div class="hours">${hours}</div>`;
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
  if (!usableUsage(usage)) return `${head}<div class="placeholder">Usage unavailable</div>`;
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
  let plugs = null;

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
      plugs.toggle((state.plugs || []).find((x) => x.id === plug.dataset.plug));
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
      plugs = createPlugToggle(el, () => ctx);
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
      plugs.close();
    },

    // First load failed and there is no state: keep the clock, show a short placeholder per tile.
    offline(c) {
      ctx = c;
      state = null;
      this.update({}, c);
      setHtml($('.hero'), `<div class="main"><div class="lbl">Next up</div><h3>${esc(OFFLINE_MESSAGE)}</h3></div>`);
      $('.hero').classList.remove('empty');
      setHtml($('.tasks'), '<div class="lbl">Tasks</div><div class="count-big">\u2014</div>');
      setHtml($('.shopping'), '<div class="lbl">Shopping</div><div class="count-big">\u2014</div>');
      showUnavailable($('.agenda'), 'Calendar unavailable');
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
      setHtml($('.weather'), weatherHtml(s.weather, now));

      const today = dayStart(now);
      const tomorrow = addDays(today, 1);
      const cols = q.querySelectorAll('.agenda .col');
      const heads = q.querySelectorAll('.ag-h');
      const events = s.events || [];
      const calendars = s.calendars || [];
      [[today, true], [tomorrow, false]].forEach(([day, isToday], i) => {
        setHtml(heads[i], `${isToday ? 'Today' : 'Tomorrow'} <span>${fmtDay(day).slice(0, 3)} ${day.getDate()}</span>`);
        setHtml(cols[i].querySelector('.items'), dayItemsHtml(events, calendars, day, now, isToday));
      });

      setHtml($('.tasks'), tasksHtml(s.tasks));
      setHtml($('.shopping'), shoppingHtml(s.shopping));
      setHtml($('.claude'), claudeHtml(s.claude, now));

      slideshow.pause(!!(s.screen && s.screen.mode === 'off'));
      const photos = s.photos || [];
      const key = photos.map((p) => p.id).join(',');
      if (key !== photoKey) {
        photoKey = key;
        slideshow.setPhotos(photos);
      }
    },
  };
}
