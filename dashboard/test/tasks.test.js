import { readFileSync } from 'node:fs';
import { makeFixtureState } from '../dev/fixtures.js';
import { createTasksView, fmtDue, isOverdue, isoLocal } from '../src/views/tasks.js';

const NOW = new Date(2026, 9, 22, 8, 42);
const css = readFileSync('src/css/views/tasks.css', 'utf8');

function setup(tweak, now = NOW) {
  const state = makeFixtureState(NOW);
  if (tweak) tweak(state);
  const el = document.createElement('section');
  document.body.appendChild(el);
  const ctx = { now: () => now, act: vi.fn(async () => {}), go: vi.fn(), toast: vi.fn() };
  const view = createTasksView();
  view.mount(el, ctx);
  view.update(state, ctx);
  return { el, ctx, view, state };
}

const col = (el, id) => el.querySelector(`[data-col="${id}"]`);
const ptr = (el, type, x = 5, y = 5, id = 1) => {
  const ev = new MouseEvent(type, { bubbles: true, clientX: x, clientY: y });
  Object.defineProperty(ev, 'pointerId', { value: id });
  el.dispatchEvent(ev);
};

describe('fmtDue', () => {
  const at = (dd, h, m = 0) => new Date(2026, 9, 22 + dd, h, m).toISOString();
  it('formats relative to now', () => {
    expect(fmtDue(at(0, 18), NOW)).toBe('today 6:00pm');
    expect(fmtDue(at(1, 0), NOW)).toBe('tomorrow');
    expect(fmtDue(at(1, 9), NOW)).toBe('tomorrow 9:00am');
    expect(fmtDue(at(3, 9), NOW)).toBe('Sunday');
    expect(fmtDue(at(6, 9), NOW)).toBe('Wednesday');
    expect(fmtDue(at(7, 9), NOW)).toBe('29 October');
  });
  it('treats a due at local midnight as date-only', () => {
    expect(fmtDue(at(0, 0), NOW)).toBe('today');
    expect(fmtDue(at(1, 0), NOW)).toBe('tomorrow');
    expect(fmtDue(at(3, 0), NOW)).toBe('Sunday');
    expect(fmtDue(at(0, 0, 1), NOW)).toBe('today 12:01am');
  });
  it('a date-only due is overdue only after its day ends; a timed one once passed', () => {
    const task = (due) => ({ id: 'x', done: false, due });
    expect(isOverdue(task(at(0, 0)), NOW)).toBe(false);
    expect(isOverdue(task(at(0, 0)), new Date(2026, 9, 22, 23, 59))).toBe(false);
    expect(isOverdue(task(at(0, 0)), new Date(2026, 9, 23, 0, 0))).toBe(true);
    expect(isOverdue(task(at(-1, 0)), NOW)).toBe(true);
    expect(isOverdue(task(at(0, 8)), NOW)).toBe(true);
    expect(isOverdue(task(at(0, 9)), NOW)).toBe(false);
    expect(isOverdue({ ...task(at(-1, 0)), done: true }, NOW)).toBe(false);
  });
  it('isoLocal carries the offset', () => {
    expect(isoLocal(new Date(2026, 9, 22, 18, 0))).toBe('2026-10-22T18:00:00+01:00');
    expect(isoLocal(new Date(2026, 11, 22, 9, 0))).toBe('2026-12-22T09:00:00+00:00');
  });
});

describe('tasks view', () => {
  afterEach(() => { document.body.innerHTML = ''; vi.useRealTimers(); });

  it('renders Alex, Vicky and Anyone columns with their tasks', () => {
    const { el } = setup();
    expect([...el.querySelectorAll('.tcol-name')].map((n) => n.textContent)).toEqual(['Alex', 'Vicky', 'Anyone']);
    ['alex', 'vicky', 'any'].forEach((id) => {
      expect(col(el, id).querySelectorAll('.task')).toHaveLength(1);
      expect(col(el, id).querySelector('.tcol-count').textContent).toBe('1');
    });
    expect(col(el, 'alex').querySelector('.task-due').textContent).toBe('today 6:00pm');
    expect(col(el, 'vicky').querySelector('.task-due').textContent).toBe('tomorrow 9:00am');
    expect(col(el, 'any').querySelector('.task-due')).toBeNull();
  });

  it('tapping a task toggles done', () => {
    const { el, ctx } = setup();
    el.querySelector('[data-tid="t1"]').click();
    expect(ctx.act).toHaveBeenCalledWith('PATCH', '/api/tasks/t1', { done: true });
  });

  it('tapping a done task marks it not done', () => {
    const { el, ctx } = setup((s) => { s.tasks[0].done = true; });
    el.querySelector('[data-tid="t1"]').click();
    expect(ctx.act).toHaveBeenCalledWith('PATCH', '/api/tasks/t1', { done: false });
  });

  it('a task due yesterday is overdue, a done one is not', () => {
    const y = new Date(2026, 9, 21, 18).toISOString();
    const { el } = setup((s) => { s.tasks[0].due = y; s.tasks[1].due = y; s.tasks[1].done = true; });
    expect(el.querySelector('[data-tid="t1"]').classList.contains('is-overdue')).toBe(true);
    expect(el.querySelector('[data-tid="t2"]').classList.contains('is-overdue')).toBe(false);
    expect(el.querySelector('[data-tid="t3"]').classList.contains('is-overdue')).toBe(false);
  });

  it('keeps a column scroll position across a data update', () => {
    const { el, view, ctx, state } = setup((s) => {
      s.tasks = Array.from({ length: 15 }, (_, i) => ({ id: `n${i}`, title: `Job ${i}`, assignee: 'alex', due: null, done: false }));
    });
    const list = col(el, 'alex').querySelector('.tcol-list');
    list.scrollTop = 120;
    state.tasks[3].done = true;
    view.update({ ...state, tasks: state.tasks.map((t) => ({ ...t })) }, ctx);
    expect(col(el, 'alex').querySelector('.tcol-list')).toBe(list);
    expect(list.querySelector('[data-tid="n3"]').classList.contains('is-done')).toBe(true);
    expect(list.scrollTop).toBe(120);
  });

  it('escapes titles', () => {
    const { el } = setup((s) => { s.tasks[0].title = '<b>x</b>'; });
    expect(el.querySelector('.tcol b')).toBeNull();
  });

  it('fifteen tasks in one column scroll inside the column', () => {
    const { el } = setup((s) => {
      s.tasks = Array.from({ length: 15 }, (_, i) => ({ id: `n${i}`, title: `Job ${i}`, assignee: 'alex', due: null, done: false }));
    });
    expect(col(el, 'alex').querySelectorAll('.task')).toHaveLength(15);
    expect(css).toMatch(/\.tcol-list\s*\{[^}]*overflow-y:\s*auto/);
    expect(css).toMatch(/\.tcol-list\s*\{[^}]*min-height:\s*0/);
    expect(css).toMatch(/\.tasks-cols\s*\{[^}]*min-height:\s*0/);
  });

  describe('long press', () => {
    it('opens a delete confirmation after 600 ms and does not toggle done', () => {
      vi.useFakeTimers();
      const { el, ctx } = setup();
      const t = el.querySelector('[data-tid="t1"]');
      ptr(t, 'pointerdown');
      vi.advanceTimersByTime(599);
      expect(el.querySelector('.sheet').hidden).toBe(true);
      vi.advanceTimersByTime(1);
      expect(el.querySelector('.sheet').hidden).toBe(false);
      expect(el.querySelector('.task-del-title').textContent).toContain('Pick up Vinted order');
      ptr(t, 'pointerup');
      t.click();
      expect(ctx.act).not.toHaveBeenCalled();
      el.querySelector('[data-delete]').click();
      expect(ctx.act).toHaveBeenCalledWith('DELETE', '/api/tasks/t1');
      expect(el.querySelector('.sheet').hidden).toBe(true);
    });

    it('Cancel closes without deleting', () => {
      vi.useFakeTimers();
      const { el, ctx } = setup();
      ptr(el.querySelector('[data-tid="t1"]'), 'pointerdown');
      vi.advanceTimersByTime(600);
      el.querySelector('.tsheet-del .sheet-close').click();
      expect(el.querySelector('.sheet').hidden).toBe(true);
      expect(ctx.act).not.toHaveBeenCalled();
    });

    it('cancels on release, move over 10 px, or pointercancel', () => {
      vi.useFakeTimers();
      const { el } = setup();
      const t = el.querySelector('[data-tid="t1"]');
      ptr(t, 'pointerdown'); vi.advanceTimersByTime(300); ptr(t, 'pointerup'); vi.advanceTimersByTime(600);
      expect(el.querySelector('.sheet').hidden).toBe(true);
      ptr(t, 'pointerdown'); ptr(t, 'pointermove', 5, 20); vi.advanceTimersByTime(600);
      expect(el.querySelector('.sheet').hidden).toBe(true);
      ptr(t, 'pointerdown'); ptr(t, 'pointermove', 8, 8); vi.advanceTimersByTime(300); ptr(t, 'pointercancel'); vi.advanceTimersByTime(600);
      expect(el.querySelector('.sheet').hidden).toBe(true);
    });
  });

  describe('add sheet', () => {
    const open = (el) => el.querySelector('[data-new]').click();
    const type = (el, v) => { const i = el.querySelector('.task-input'); i.value = v; i.dispatchEvent(new Event('input', { bubbles: true })); };

    it('is disabled while the title is empty', () => {
      const { el, ctx } = setup();
      open(el);
      const go = el.querySelector('[data-submit]');
      expect(go.disabled).toBe(true);
      go.click();
      expect(ctx.act).not.toHaveBeenCalled();
      type(el, '   ');
      expect(go.disabled).toBe(true);
      type(el, 'Call the plumber');
      expect(go.disabled).toBe(false);
    });

    it('defaults to Anyone with no due date', () => {
      const { el, ctx } = setup();
      open(el);
      type(el, ' Call the plumber ');
      el.querySelector('[data-submit]').click();
      expect(ctx.act).toHaveBeenCalledWith('POST', '/api/tasks', { title: 'Call the plumber', assignee: 'any', due: null });
      expect(el.querySelector('.sheet').hidden).toBe(true);
    });

    it('preset chip, assignee and today-evening need no typing', () => {
      const { el, ctx } = setup();
      open(el);
      el.querySelector('[data-preset="Bins out"]').click();
      el.querySelector('[data-who="vicky"]').click();
      el.querySelector('[data-due="tonight"]').click();
      el.querySelector('[data-submit]').click();
      expect(ctx.act).toHaveBeenCalledWith('POST', '/api/tasks',
        { title: 'Bins out', assignee: 'vicky', due: '2026-10-22T18:00:00+01:00' });
    });

    it('tomorrow is date-only: local midnight (BST)', () => {
      const { el, ctx } = setup();
      open(el);
      type(el, 'x');
      el.querySelector('[data-who="alex"]').click();
      el.querySelector('[data-due="tomorrow"]').click();
      el.querySelector('[data-submit]').click();
      expect(ctx.act.mock.calls[0][2]).toEqual({ title: 'x', assignee: 'alex', due: '2026-10-23T00:00:00+01:00' });
    });

    it('tomorrow is local midnight in GMT, and across the clock change', () => {
      for (const [now, due] of [
        [new Date(2026, 11, 22, 8, 0), '2026-12-23T00:00:00+00:00'],
        [new Date(2026, 9, 24, 20, 0), '2026-10-25T00:00:00+01:00'],
      ]) {
        const { el, ctx } = setup(null, now);
        open(el);
        type(el, 'x');
        el.querySelector('[data-due="tomorrow"]').click();
        el.querySelector('[data-submit]').click();
        expect(ctx.act.mock.calls[0][2].due).toBe(due);
        expect(fmtDue(due, now)).toBe('tomorrow');
      }
    });

    it('pick time uses the datetime-local input and needs a value', () => {
      const { el, ctx } = setup();
      open(el);
      type(el, 'x');
      const pick = el.querySelector('.task-pick');
      expect(pick.type).toBe('datetime-local');
      expect(pick.hidden).toBe(true);
      el.querySelector('[data-due="pick"]').click();
      expect(pick.hidden).toBe(false);
      expect(el.querySelector('[data-submit]').disabled).toBe(true);
      pick.value = '2026-10-30T14:30';
      pick.dispatchEvent(new Event('input', { bubbles: true }));
      expect(el.querySelector('[data-submit]').disabled).toBe(false);
      el.querySelector('[data-submit]').click();
      expect(ctx.act.mock.calls[0][2].due).toBe('2026-10-30T14:30:00+00:00');
    });

    it('keeps typed text across state updates', () => {
      const { el, view, ctx, state } = setup();
      open(el);
      type(el, 'draft');
      view.update(state, ctx);
      expect(el.querySelector('.task-input').value).toBe('draft');
      expect(el.querySelector('.sheet').hidden).toBe(false);
    });
  });
});
