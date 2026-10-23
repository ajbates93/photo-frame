import { makeFixtureState } from '../dev/fixtures.js';
import { createClaudeView } from '../src/views/claude.js';

const NOW = new Date(2026, 9, 22, 8, 42);
const ago = (m) => new Date(NOW.getTime() - m * 60000).toISOString();

function setup(tweak) {
  const state = makeFixtureState(NOW);
  if (tweak) tweak(state);
  const el = document.createElement('section');
  document.body.appendChild(el);
  const ctx = { now: () => NOW, act: vi.fn(), go: vi.fn(), toast: vi.fn() };
  const view = createClaudeView();
  view.mount(el, ctx);
  view.update(state, ctx);
  return { el };
}

describe('claude view', () => {
  afterEach(() => { document.body.innerHTML = ''; });

  it('lists waiting sessions first, then working, then done, newest first within a group', () => {
    const { el } = setup((s) => {
      s.claude.sessions = [
        { id: 'a', project: 'done-old', state: 'done', since: ago(90) },
        { id: 'b', project: 'work-old', state: 'working', since: ago(30) },
        { id: 'c', project: 'wait-old', state: 'waiting', since: ago(20) },
        { id: 'd', project: 'wait-new', state: 'waiting', since: ago(2) },
        { id: 'e', project: 'work-new', state: 'working', since: ago(5) },
      ];
    });
    expect([...el.querySelectorAll('.cl-project')].map((n) => n.textContent))
      .toEqual(['wait-new', 'wait-old', 'work-new', 'work-old', 'done-old']);
    expect([...el.querySelectorAll('.cl-chip')].map((n) => n.textContent))
      .toEqual(['Needs you', 'Needs you', 'Working', 'Working', 'Done']);
    expect(el.querySelector('.cl-time').textContent).toBe('2 min');
  });

  it('shows Usage unavailable when usage is null', () => {
    const { el } = setup((s) => { s.claude.usage = null; });
    expect(el.textContent).toContain('Usage unavailable');
    expect(el.querySelector('.cl-meter')).toBeNull();
  });

  it('shows Usage unavailable when a meter is missing or malformed', () => {
    for (const tweak of [
      (u) => { u.session = null; },
      (u) => { delete u.weekly; },
      (u) => { u.weekly.resetsAt = 'never'; },
      (u) => { u.session.pct = null; },
    ]) {
      const { el } = setup((s) => tweak(s.claude.usage));
      expect(el.querySelector('.cl-usage').textContent).toBe('Usage unavailable');
      expect(el.textContent).not.toContain('NaN');
      expect(el.querySelector('.cl-plan').textContent).toBe('Max plan');
      document.body.innerHTML = '';
    }
  });

  it('shows 42% resetting in 1h 18m with an even-pace marker at 74%', () => {
    const { el } = setup();
    const m = el.querySelector('.cl-meter');
    expect(m.querySelector('.cl-pct').textContent).toBe('42% used');
    expect(m.querySelector('.cl-reset').textContent).toBe('resets in 1h 18m');
    expect(m.querySelector('.cl-pace').style.left).toBe('74%');
    expect(el.querySelectorAll('.cl-meter')).toHaveLength(2);
  });

  it('escapes project names', () => {
    const { el } = setup((s) => { s.claude.sessions[0].project = '<img src=x>'; });
    expect(el.querySelector('.cl-session img')).toBeNull();
  });
});
