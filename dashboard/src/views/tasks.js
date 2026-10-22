import '../css/views/tasks.css';
import { fmtTime, fmtDay, fmtDate, dayStart, addDays } from '../lib/time.js';
import { esc, setHtml, validColor } from '../ui/html.js';

const LONG_PRESS_MS = 600;
const MOVE_PX = 10;
const PRESETS = ['Bins out', 'Water the plants', 'Tidy up', 'Recycling'];
const DUES = [['none', 'None'], ['tonight', 'Today evening'], ['tomorrow', 'Tomorrow'], ['pick', 'Pick time']];

const pad = (n) => String(n).padStart(2, '0');

// ISO 8601 with the local UTC offset, e.g. 2026-10-22T18:00:00+01:00.
export function isoLocal(d) {
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? '+' : '-';
  const a = Math.abs(off);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}${sign}${pad(Math.floor(a / 60))}:${pad(a % 60)}`;
}

const dayDiff = (a, b) => Math.round(
  (Date.UTC(a.getFullYear(), a.getMonth(), a.getDate()) - Date.UTC(b.getFullYear(), b.getMonth(), b.getDate())) / 86400000,
);

// A due at exactly local midnight is date-only (no time shown; due all that day).
const dateOnly = (d) => d.getHours() === 0 && d.getMinutes() === 0 && d.getSeconds() === 0;

// Due label relative to `now`: today 6:00pm / today / tomorrow / Saturday / 5 November.
export function fmtDue(due, now) {
  const d = new Date(due);
  if (Number.isNaN(d.getTime())) return '';
  const diff = dayDiff(d, now);
  const timed = !dateOnly(d);
  if (diff === 0) return timed ? `today ${fmtTime(d)}` : 'today';
  if (diff === 1) return timed ? `tomorrow ${fmtTime(d)}` : 'tomorrow';
  if (diff >= 2 && diff <= 6) return fmtDay(d);
  return fmtDate(d);
}

// Timed dues are overdue once passed; date-only dues only after their day ends.
export function isOverdue(t, now) {
  if (t.done || !t.due) return false;
  const d = new Date(t.due);
  if (Number.isNaN(d.getTime())) return false;
  return (dateOnly(d) ? addDays(d, 1) : d) <= now;
}

function taskHtml(t, now) {
  const over = isOverdue(t, now);
  const due = t.due ? fmtDue(t.due, now) : '';
  return `<button type="button" class="task${t.done ? ' is-done' : ''}${over ? ' is-overdue' : ''}" data-tid="${esc(t.id)}">`
    + '<span class="task-box"></span><span class="task-body">'
    + `<span class="task-title">${esc(t.title)}</span>`
    + (due ? `<span class="task-due">${esc(due)}</span>` : '')
    + '</span></button>';
}

function sortTasks(list) {
  const key = (t) => (t.due ? new Date(t.due).getTime() || Infinity : Infinity);
  return list.slice().sort((a, b) => (a.done - b.done) || (key(a) - key(b)));
}

const SKELETON = `
<div class="tasks">
  <div class="tasks-head">
    <h2>Tasks</h2>
    <button type="button" class="task-btn task-new" data-new>Add task</button>
  </div>
  <div class="tasks-cols"></div>
  <div class="sheet" hidden>
    <div class="sheet-back"></div>
    <div class="sheet-card" role="dialog" aria-modal="true">
      <div class="tsheet-add" hidden>
        <h3>New task</h3>
        <input type="text" class="task-input" placeholder="What needs doing?" autocomplete="off" maxlength="120" aria-label="Task title">
        <div class="task-opts task-presets">${PRESETS.map((p) => `<button type="button" class="task-opt" data-preset="${esc(p)}">${esc(p)}</button>`).join('')}</div>
        <div class="task-label">Who</div>
        <div class="task-opts task-who"></div>
        <div class="task-label">When</div>
        <div class="task-opts task-when">${DUES.map(([k, l]) => `<button type="button" class="task-opt" data-due="${k}">${l}</button>`).join('')}</div>
        <input type="datetime-local" class="task-input task-pick" hidden aria-label="Due date and time">
        <div class="task-actions">
          <button type="button" class="task-btn sheet-close">Cancel</button>
          <button type="button" class="task-btn task-go" data-submit disabled>Add</button>
        </div>
      </div>
      <div class="tsheet-del" hidden>
        <h3 class="task-del-title"></h3>
        <div class="task-actions">
          <button type="button" class="task-btn sheet-close">Cancel</button>
          <button type="button" class="task-btn task-danger" data-delete>Delete</button>
        </div>
      </div>
    </div>
  </div>
</div>`;

export function createTasksView() {
  let q = null;
  let ctx = null;
  let state = null;
  let draft = null; // { assignee, due, pick }
  let delId = null;
  let press = null; // { timer, id, x, y, pointerId }
  let longFired = false;

  const $ = (sel) => q.querySelector(sel);

  function columns() {
    const people = (state && state.people) || [];
    const cols = people.map((p) => ({ id: p.id, name: p.name, color: validColor(p.color) }));
    cols.push({ id: 'any', name: 'Anyone', color: null });
    return cols;
  }

  function render() {
    if (!state || !q) return;
    const now = ctx.now();
    const cols = columns();
    const known = new Set(cols.map((c) => c.id));
    const tasks = state.tasks || [];
    // Column shells persist (keyed by column ids) so each list keeps its scroll position.
    const host = $('.tasks-cols');
    const key = cols.map((c) => c.id).join('|');
    if (host.dataset.key !== key) {
      host.dataset.key = key;
      host.innerHTML = cols.map((c) => `<div class="tcol" data-col="${esc(c.id)}"><div class="tcol-head"></div><div class="tcol-list"></div></div>`).join('');
    }
    const shells = host.children;
    cols.forEach((c, i) => {
      const mine = sortTasks(tasks.filter((t) => (known.has(t.assignee) ? t.assignee : 'any') === c.id));
      const open = mine.filter((t) => !t.done).length;
      setHtml(shells[i].firstElementChild, `<i class="dot" style="background:${c.color || 'var(--fam)'}"></i>`
        + `<span class="tcol-name">${esc(c.name)}</span><span class="tcol-count">${open}</span>`);
      setHtml(shells[i].lastElementChild, mine.map((t) => taskHtml(t, now)).join('') || '<div class="tcol-empty">Nothing to do</div>');
    });
    if (draft) syncAdd();
  }

  function closeSheet() {
    $('.sheet').hidden = true;
    $('.tsheet-add').hidden = true;
    $('.tsheet-del').hidden = true;
    draft = null;
    delId = null;
  }

  function dueIso() {
    if (draft.due === 'none') return { ok: true, value: null };
    const now = ctx.now();
    if (draft.due === 'tonight') {
      return { ok: true, value: isoLocal(new Date(now.getFullYear(), now.getMonth(), now.getDate(), 18, 0, 0, 0)) };
    }
    if (draft.due === 'tomorrow') {
      const d = addDays(dayStart(now), 1);
      return { ok: true, value: isoLocal(new Date(d.getFullYear(), d.getMonth(), d.getDate(), 9, 0, 0, 0)) };
    }
    const p = draft.pick ? new Date(draft.pick) : null;
    return p && !Number.isNaN(p.getTime()) ? { ok: true, value: isoLocal(p) } : { ok: false, value: null };
  }

  function syncAdd() {
    const title = $('.task-input').value.trim();
    q.querySelectorAll('[data-who]').forEach((b) => b.classList.toggle('is-on', b.dataset.who === draft.assignee));
    q.querySelectorAll('[data-due]').forEach((b) => b.classList.toggle('is-on', b.dataset.due === draft.due));
    $('.task-pick').hidden = draft.due !== 'pick';
    $('.task-go').disabled = !title || !dueIso().ok;
  }

  function openAdd() {
    draft = { assignee: 'any', due: 'none', pick: '' };
    $('.task-input').value = '';
    $('.task-pick').value = '';
    setHtml($('.task-who'), columns()
      .map((c) => `<button type="button" class="task-opt" data-who="${esc(c.id)}">${esc(c.name)}</button>`).join(''));
    $('.tsheet-del').hidden = true;
    $('.tsheet-add').hidden = false;
    $('.sheet').hidden = false;
    syncAdd();
  }

  function openDelete(id) {
    const t = ((state && state.tasks) || []).find((x) => x.id === id);
    if (!t) return;
    delId = id;
    setHtml($('.task-del-title'), `Delete “${esc(t.title)}”?`);
    $('.tsheet-add').hidden = true;
    $('.tsheet-del').hidden = false;
    $('.sheet').hidden = false;
  }

  async function submit() {
    if (!draft) return;
    const title = $('.task-input').value.trim();
    const due = dueIso();
    if (!title || !due.ok) return;
    const body = { title, assignee: draft.assignee, due: due.value };
    closeSheet();
    await ctx.act('POST', '/api/tasks', body);
  }

  function cancelPress() {
    if (press) clearTimeout(press.timer);
    press = null;
  }

  function onDown(e) {
    const t = e.target.closest ? e.target.closest('[data-tid]') : null;
    longFired = false;
    if (!t || press) return;
    const id = t.dataset.tid;
    press = {
      id, x: e.clientX, y: e.clientY, pointerId: e.pointerId,
      timer: setTimeout(() => {
        press = null;
        longFired = true;
        openDelete(id);
      }, LONG_PRESS_MS),
    };
  }

  function onMove(e) {
    if (!press || e.pointerId !== press.pointerId) return;
    if (Math.hypot(e.clientX - press.x, e.clientY - press.y) > MOVE_PX) cancelPress();
  }

  function onUp(e) {
    if (press && e.pointerId === press.pointerId) cancelPress();
  }

  function onClick(e) {
    const t = e.target;
    // The release that ends a long press lands on the task or the new backdrop: swallow it.
    if (longFired) {
      longFired = false;
      if (t.closest('[data-tid]') || t.closest('.sheet-back')) return;
    }
    if (t.closest('.sheet-close') || t.closest('.sheet-back')) { closeSheet(); return; }
    if (t.closest('[data-new]')) { openAdd(); return; }
    if (t.closest('[data-submit]')) { submit(); return; }
    if (t.closest('[data-delete]')) {
      const id = delId;
      closeSheet();
      if (id) ctx.act('DELETE', `/api/tasks/${encodeURIComponent(id)}`);
      return;
    }
    if (draft) {
      const preset = t.closest('[data-preset]');
      if (preset) { $('.task-input').value = preset.dataset.preset; syncAdd(); return; }
      const who = t.closest('[data-who]');
      if (who) { draft.assignee = who.dataset.who; syncAdd(); return; }
      const due = t.closest('[data-due]');
      if (due) { draft.due = due.dataset.due; syncAdd(); return; }
    }
    const row = t.closest('[data-tid]');
    if (row) {
      const task = ((state && state.tasks) || []).find((x) => x.id === row.dataset.tid);
      if (task) ctx.act('PATCH', `/api/tasks/${encodeURIComponent(task.id)}`, { done: !task.done });
    }
  }

  function onInput(e) {
    if (!draft) return;
    if (e.target.closest('.task-pick')) draft.pick = e.target.value;
    syncAdd();
  }

  return {
    mount(el, c) {
      ctx = c;
      el.innerHTML = SKELETON;
      q = el;
      el.addEventListener('click', onClick);
      el.addEventListener('input', onInput);
      el.addEventListener('change', onInput);
      el.addEventListener('pointerdown', onDown);
      el.addEventListener('pointermove', onMove);
      el.addEventListener('pointerup', onUp);
      el.addEventListener('pointercancel', cancelPress);
    },

    show(c) {
      if (c) ctx = c;
      closeSheet();
      render();
    },

    hide() { cancelPress(); closeSheet(); },

    update(s, c) {
      ctx = c;
      state = s;
      render();
    },
  };
}
