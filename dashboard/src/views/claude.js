import '../css/views/claude.css';
import { fmtCountdown, fmtResetsIn } from '../lib/time.js';
import { usableUsage } from '../lib/usage.js';
import { esc, setHtml } from '../ui/html.js';

const SESSION_WINDOW_MINS = 5 * 60;
const WEEKLY_WINDOW_MINS = 7 * 24 * 60;
const ORDER = { waiting: 0, working: 1, done: 2 };
const CHIP = { waiting: 'Needs you', working: 'Working', done: 'Done' };

const SKELETON = `
<div class="claude">
  <div class="cl-head"><h2>Claude</h2><span class="cl-plan"></span></div>
  <div class="cl-usage"></div>
  <div class="cl-label">Sessions</div>
  <div class="cl-sessions"></div>
</div>`;

const minsBetween = (a, b) => (new Date(a) - b) / 60000;

export function paceOf(minsLeft, windowMins) {
  const pct = (1 - minsLeft / windowMins) * 100;
  return Math.max(0, Math.min(100, Number.isFinite(pct) ? pct : 0));
}

function meterHtml(label, m, windowMins, now) {
  const pct = Math.max(0, Math.min(100, Math.round(Number(m.pct) || 0)));
  const left = Math.max(0, minsBetween(m.resetsAt, now));
  const pace = Math.round(paceOf(Number.isFinite(left) ? left : 0, windowMins));
  return `<div class="cl-meter"><div class="cl-meter-top"><span>${esc(label)}</span><b class="cl-pct">${pct}%</b></div>`
    + `<div class="cl-bar"><i style="width:${pct}%"></i><em class="cl-pace" style="left:${pace}%" title="Even pace"></em></div>`
    + `<div class="cl-reset">resets in ${fmtResetsIn(left)}</div></div>`;
}

function usageHtml(usage, now) {
  if (!usableUsage(usage)) return '<div class="cl-none">Usage unavailable</div>';
  return meterHtml('Session', usage.session, SESSION_WINDOW_MINS, now)
    + meterHtml('Weekly', usage.weekly, WEEKLY_WINDOW_MINS, now);
}

export function sortSessions(sessions) {
  const t = (s) => new Date(s.since).getTime() || 0;
  return sessions.slice().sort((a, b) => ((ORDER[a.state] ?? 3) - (ORDER[b.state] ?? 3)) || (t(b) - t(a)));
}

function sessionsHtml(sessions, now) {
  if (!sessions.length) return '<div class="cl-none">No sessions</div>';
  return sortSessions(sessions).map((s) => {
    const mins = Math.max(0, -minsBetween(s.since, now) || 0);
    const state = ORDER[s.state] === undefined ? 'done' : s.state;
    return `<div class="cl-session is-${state}"><span class="cl-project">${esc(s.project)}</span>`
      + `<span class="cl-chip">${CHIP[state]}</span><span class="cl-time">${fmtCountdown(mins)}</span></div>`;
  }).join('');
}

export function createClaudeView() {
  let q = null;
  const $ = (sel) => q.querySelector(sel);

  return {
    mount(el) {
      q = el;
      el.innerHTML = SKELETON;
    },
    update(s, c) {
      const claude = s.claude || {};
      const now = c.now();
      const usage = claude.usage || null;
      setHtml($('.cl-plan'), usage && usage.plan ? `${esc(usage.plan)} plan` : '');
      setHtml($('.cl-usage'), usageHtml(usage, now));
      setHtml($('.cl-sessions'), sessionsHtml(claude.sessions || [], now));
    },
  };
}
