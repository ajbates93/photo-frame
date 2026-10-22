import { makeFixtureState } from '../dev/fixtures.js';
import { createControlView } from '../src/views/control.js';

const NOW = new Date(2026, 9, 22, 8, 42);

function setup(tweak) {
  const state = makeFixtureState(NOW);
  if (tweak) tweak(state);
  const el = document.createElement('section');
  document.body.appendChild(el);
  const ctx = { now: () => NOW, act: vi.fn(async () => true), go: vi.fn(), toast: vi.fn() };
  const view = createControlView();
  view.mount(el, ctx);
  view.update(state, ctx);
  return { el, ctx, view, state };
}

describe('control view', () => {
  afterEach(() => { document.body.innerHTML = ''; });

  it('groups four plugs into three rooms in order of first appearance', () => {
    const { el } = setup();
    expect([...el.querySelectorAll('.ctl-room-name')].map((n) => n.textContent)).toEqual(['Living room', 'Office', 'Bedroom']);
    expect(el.querySelectorAll('.cplug')).toHaveLength(4);
  });

  it('does not render hidden plugs', () => {
    const { el } = setup((s) => { s.plugs[3].hidden = true; });
    expect(el.querySelector('[data-plug="pl4"]')).toBeNull();
    expect(el.querySelectorAll('.ctl-room')).toHaveLength(2);
  });

  it('toggles a plain plug straight away', () => {
    const { el, ctx } = setup();
    el.querySelector('[data-plug="pl1"]').click();
    expect(ctx.act).toHaveBeenCalledWith('POST', '/api/plugs/pl1', { on: false });
    el.querySelector('[data-plug="pl2"]').click();
    expect(ctx.act).toHaveBeenCalledWith('POST', '/api/plugs/pl2', { on: true });
  });

  it('asks before turning a confirm plug off, escaping the name', () => {
    const { el, ctx } = setup((s) => { s.plugs[0].confirm = true; s.plugs[0].name = '<b>Lamp</b>'; });
    el.querySelector('[data-plug="pl1"]').click();
    expect(ctx.act).not.toHaveBeenCalled();
    expect(el.querySelector('.sheet').hidden).toBe(false);
    expect(el.querySelector('.confirm-title').textContent).toBe('Turn off <b>Lamp</b>?');
    expect(el.querySelector('.confirm-title b')).toBeNull();
    el.querySelector('[data-confirm]').click();
    expect(ctx.act).toHaveBeenCalledWith('POST', '/api/plugs/pl1', { on: false });
    expect(el.querySelector('.sheet').hidden).toBe(true);
  });

  it('cancel closes the sheet without acting; turning a confirm plug on does not ask', () => {
    const { el, ctx } = setup((s) => { s.plugs[0].confirm = true; s.plugs[1].confirm = true; });
    el.querySelector('[data-plug="pl1"]').click();
    el.querySelector('.sheet-close').click();
    expect(el.querySelector('.sheet').hidden).toBe(true);
    expect(ctx.act).not.toHaveBeenCalled();
    el.querySelector('[data-plug="pl2"]').click();
    expect(ctx.act).toHaveBeenCalledWith('POST', '/api/plugs/pl2', { on: true });
  });

  it('an unreachable plug shows Offline and ignores clicks', () => {
    const { el, ctx } = setup((s) => { s.plugs[0].reachable = false; });
    const b = el.querySelector('[data-plug="pl1"]');
    expect(b.textContent).toContain('Offline');
    b.click();
    b.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(ctx.act).not.toHaveBeenCalled();
  });

  it('volume + at 40 sends 50, then - from 50 sends 40, and it clamps at 100', () => {
    const { el, ctx, view, state } = setup();
    el.querySelector('[data-vol="1"]').click();
    expect(ctx.act).toHaveBeenCalledWith('POST', '/api/speaker', { action: 'volume', volume: 50 });
    state.speaker.volume = 50;
    view.update(state, ctx);
    el.querySelector('[data-vol="-1"]').click();
    expect(ctx.act).toHaveBeenCalledWith('POST', '/api/speaker', { action: 'volume', volume: 40 });
    state.speaker.volume = 40;
    view.update(state, ctx); // server caught up
    state.speaker.volume = 100;
    view.update(state, ctx);
    el.querySelector('[data-vol="1"]').click();
    expect(ctx.act).toHaveBeenLastCalledWith('POST', '/api/speaker', { action: 'volume', volume: 100 });
  });

  it('quick + taps step from the last pressed level and show it before the server answers', () => {
    const { el, ctx, view, state } = setup();
    el.querySelector('[data-vol="1"]').click();
    el.querySelector('[data-vol="1"]').click();
    expect(ctx.act.mock.calls.map((c) => c[2].volume)).toEqual([50, 60]);
    expect(el.querySelector('.sp-level span').textContent).toBe('60%');
    view.update(state, ctx); // stale server value (40) does not undo the display
    expect(el.querySelector('.sp-level span').textContent).toBe('60%');
    state.speaker.volume = 60;
    view.update(state, ctx); // server caught up: pending cleared
    state.speaker.volume = 20;
    view.update(state, ctx);
    expect(el.querySelector('.sp-level span').textContent).toBe('20%');
  });

  it('pending volume expires after about 3 s', () => {
    vi.useFakeTimers();
    try {
      const { el } = setup();
      el.querySelector('[data-vol="1"]').click();
      expect(el.querySelector('.sp-level span').textContent).toBe('50%');
      vi.advanceTimersByTime(3100);
      expect(el.querySelector('.sp-level span').textContent).toBe('40%');
    } finally { vi.useRealTimers(); }
  });

  it('shows the track and a pause button while playing; play when paused', () => {
    const { el, ctx, view, state } = setup();
    expect(el.querySelector('.sp-title').textContent).toBe('Morning Mix');
    el.querySelector('[data-sp]').click();
    expect(ctx.act).toHaveBeenCalledWith('POST', '/api/speaker', { action: 'pause' });
    state.speaker.playing = false;
    state.speaker.title = null;
    view.update(state, ctx);
    expect(el.querySelector('.sp-title').textContent).toBe('Nothing playing');
    el.querySelector('[data-sp]').click();
    expect(ctx.act).toHaveBeenLastCalledWith('POST', '/api/speaker', { action: 'play' });
  });

  it('unreachable speaker shows Offline with inert controls; null speaker shows unavailable', () => {
    const { el, ctx, view, state } = setup((s) => { s.speaker.reachable = false; });
    expect(el.querySelector('.ctl-speaker').textContent).toContain('Kitchen speaker');
    expect(el.querySelector('.ctl-speaker').textContent).toContain('Offline');
    el.querySelector('[data-vol="1"]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(ctx.act).not.toHaveBeenCalled();
    state.speaker = null;
    view.update(state, ctx);
    expect(el.querySelector('.ctl-speaker').textContent).toContain('Speaker unavailable');
  });
});
