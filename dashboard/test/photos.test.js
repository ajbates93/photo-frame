import { makeFixtureState } from '../dev/fixtures.js';
import { createPhotosView } from '../src/views/photos.js';

const NOW = new Date(2026, 9, 22, 8, 42);

describe('photos view', () => {
  afterEach(() => { document.body.innerHTML = ''; document.documentElement.className = ''; vi.useRealTimers(); });

  function setup() {
    vi.useFakeTimers();
    const el = document.createElement('section');
    document.body.appendChild(el);
    const ctx = { now: () => NOW, act: vi.fn(), go: vi.fn(), toast: vi.fn() };
    const view = createPhotosView();
    view.mount(el, ctx);
    view.update(makeFixtureState(NOW), ctx);
    return { el, view };
  }

  it('hides the rail 5 s after show, restores on tap and on hide', () => {
    const { el, view } = setup();
    const root = document.documentElement;
    view.show();
    vi.advanceTimersByTime(4900);
    expect(root.classList.contains('rail-hidden')).toBe(false);
    vi.advanceTimersByTime(200);
    expect(root.classList.contains('rail-hidden')).toBe(true);
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(root.classList.contains('rail-hidden')).toBe(false);
    vi.advanceTimersByTime(5100);
    expect(root.classList.contains('rail-hidden')).toBe(true);
    view.hide();
    expect(root.classList.contains('rail-hidden')).toBe(false);
    vi.advanceTimersByTime(10000);
    expect(root.classList.contains('rail-hidden')).toBe(false);
  });

  it('keeps at most two slideshow images', () => {
    const { el, view } = setup();
    view.show();
    expect(el.querySelectorAll('img')).toHaveLength(2);
    view.hide();
  });

  it('stops its timers and drops its images on hide', () => {
    const { el, view } = setup();
    view.show();
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    view.hide();
    expect(vi.getTimerCount()).toBe(0);
    expect(el.querySelectorAll('img')).toHaveLength(0);
  });
});
