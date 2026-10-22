import { GRID, layoutDay, allDayOn } from '../lib/calendar.js';
import { fmtTime, fmtHour, fmtRange } from '../lib/time.js';
import { esc, validColor, tint } from './html.js';
import '../css/agenda.css';

const SPAN = GRID.endHour - GRID.startHour;

// Hour lines (solid) and half-hour lines (dashed) for one day column.
export function hourLinesHtml() {
  let out = '';
  for (let h = GRID.startHour + 1; h < GRID.endHour; h += 1) {
    out += `<div class="hl" style="top:${(((h - GRID.startHour) / SPAN) * 100).toFixed(3)}%"></div>`;
    out += `<div class="hl half" style="top:${(((h - 0.5 - GRID.startHour) / SPAN) * 100).toFixed(3)}%"></div>`;
  }
  return out;
}

export function gutterHtml() {
  let out = '';
  for (let h = GRID.startHour + 1; h < GRID.endHour; h += 1) {
    out += `<div style="top:${(((h - GRID.startHour) / SPAN) * 100).toFixed(3)}%">${fmtHour(h)}</div>`;
  }
  return out;
}

function blockHtml(b, cal) {
  const e = b.event;
  const start = new Date(e.start);
  const end = new Date(e.end);
  const oneLine = b.short || b.clampedStart || b.clampedEnd;
  const color = validColor(cal && cal.color);
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
  return `<div class="${cls}" data-eid="${esc(e.id)}" style="${style}">${inner}</div>`;
}

// Contents of one day column's .items layer: all-day strip, event blocks, optional now line.
export function dayItemsHtml(events, calendars, day, now, isToday) {
  const calOf = (e) => calendars.find((c) => c.id === e.calendarId);
  const allDay = allDayOn(events, day)
    .map((e) => `<div class="allday" data-eid="${esc(e.id)}">${esc(e.title)}</div>`).join('');
  const blocks = layoutDay(events, day, now).map((b) => blockHtml(b, calOf(b.event))).join('');
  let nowLine = '';
  if (isToday) {
    const h = now.getHours() + now.getMinutes() / 60;
    if (h >= GRID.startHour && h <= GRID.endHour) {
      const pct = ((h - GRID.startHour) / SPAN) * 100;
      nowLine = `<div class="now" style="top:${pct.toFixed(2)}%"></div>`;
    }
  }
  return (allDay ? `<div class="alldays">${allDay}</div>` : '') + blocks + nowLine;
}
