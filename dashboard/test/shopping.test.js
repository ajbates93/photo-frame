import { readFileSync } from 'node:fs';
import { makeFixtureState } from '../dev/fixtures.js';
import { createShoppingView, quickAddChips } from '../src/views/shopping.js';

const NOW = new Date(2026, 9, 22, 8, 42);
const css = readFileSync('src/css/views/shopping.css', 'utf8');

function setup(tweak) {
  const state = makeFixtureState(NOW);
  if (tweak) tweak(state);
  const el = document.createElement('section');
  document.body.appendChild(el);
  const ctx = { now: () => NOW, act: vi.fn(async () => {}), go: vi.fn(), toast: vi.fn() };
  const view = createShoppingView();
  view.mount(el, ctx);
  view.update(state, ctx);
  return { el, ctx, view, state };
}

const rule = (sel) => new RegExp(`${sel.replace('.', '\\.')}\\s*\\{[^}]*\\}`).exec(css)[0];

describe('shopping view', () => {
  afterEach(() => { document.body.innerHTML = ''; });

  it('lists unchecked items first, then checked ones under Done', () => {
    const { el, state } = setup();
    const rows = [...el.querySelectorAll('.shop-item')];
    expect(rows).toHaveLength(state.shopping.items.length);
    const flags = rows.map((r) => r.classList.contains('is-checked'));
    expect(flags).toEqual([...flags].sort((a, b) => a - b));
    expect(flags.filter(Boolean)).toHaveLength(2);
    expect(el.querySelector('.shop-sub').textContent).toBe('Done');
    expect(el.querySelector('.shop-sub').nextElementSibling.classList.contains('is-checked')).toBe(true);
  });

  it('tapping an unchecked item checks it', () => {
    const { el, ctx, state } = setup();
    const item = state.shopping.items.find((i) => !i.checked);
    el.querySelector(`[data-iid="${item.id}"]`).click();
    expect(ctx.act).toHaveBeenCalledWith('PATCH', `/api/shopping/items/${item.id}`, { checked: true });
  });

  it('tapping a checked item unchecks it', () => {
    const { el, ctx, state } = setup();
    const item = state.shopping.items.find((i) => i.checked);
    el.querySelector(`[data-iid="${item.id}"]`).click();
    expect(ctx.act).toHaveBeenCalledWith('PATCH', `/api/shopping/items/${item.id}`, { checked: false });
  });

  it('encodes item ids in the URL', () => {
    const { el, ctx } = setup((s) => { s.shopping.items[0].id = 'a/b c'; });
    el.querySelector('[data-iid]').click();
    expect(ctx.act.mock.calls[0][1]).toBe('/api/shopping/items/a%2Fb%20c');
  });

  it('Add posts trimmed text, ignores empty input, and clears the field', async () => {
    const { el, ctx } = setup();
    const input = el.querySelector('.shop-input');
    el.querySelector('[data-add]').click();
    input.value = '   ';
    el.querySelector('[data-add]').click();
    expect(ctx.act).not.toHaveBeenCalled();
    input.value = '  Oat milk ';
    el.querySelector('[data-add]').click();
    expect(ctx.act).toHaveBeenCalledWith('POST', '/api/shopping/items', { text: 'Oat milk' });
    await Promise.resolve();
    await Promise.resolve();
    expect(input.value).toBe('');
  });

  it('quick-add chips come from checked items and post on tap', () => {
    const { el, ctx, state } = setup();
    const chips = [...el.querySelectorAll('.shop-chip')].map((c) => c.textContent);
    expect(chips).toEqual(state.shopping.items.filter((i) => i.checked).map((i) => i.text));
    el.querySelector('.shop-chip').click();
    expect(ctx.act).toHaveBeenCalledWith('POST', '/api/shopping/items', { text: chips[0] });
  });

  it('chips de-duplicate case-insensitively and cap at eight', () => {
    const items = Array.from({ length: 12 }, (_, i) => ({ id: `i${i}`, text: `Item ${i}`, checked: true }));
    items.push({ id: 'x', text: 'ITEM 0', checked: true }, { id: 'y', text: 'unchecked', checked: false });
    const chips = quickAddChips(items);
    expect(chips).toHaveLength(8);
    expect(chips).not.toContain('ITEM 0');
    expect(quickAddChips([{ text: 'Milk', checked: true }, { text: 'milk', checked: true }])).toEqual(['Milk']);
  });

  it('shows the stale note only when stale', () => {
    const fresh = setup();
    expect(fresh.el.querySelector('.shop-stale').hidden).toBe(true);
    document.body.innerHTML = '';
    const { el } = setup((s) => { s.shopping.stale = true; });
    const note = el.querySelector('.shop-stale');
    expect(note.hidden).toBe(false);
    expect(note.textContent).toContain('Out of sync with Keep');
    expect(note.textContent).toContain('8:42am');
  });

  it('escapes item text', () => {
    const { el } = setup((s) => { s.shopping.items[0].text = '<img src=x onerror=alert(1)>'; });
    expect(el.querySelector('img')).toBeNull();
    expect(el.querySelector('.shop-text').textContent).toBe('<img src=x onerror=alert(1)>');
  });

  it('with 25 items the list scrolls inside a panel whose height is unchanged', () => {
    const { el, view, ctx, state } = setup();
    const panel = el.querySelector('.shop-list');
    const before = panel.getAttribute('style');
    state.shopping.items = Array.from({ length: 25 }, (_, i) => ({ id: `n${i}`, text: `Thing ${i}`, checked: i % 5 === 0 }));
    view.update(state, ctx);
    expect(el.querySelectorAll('.shop-item')).toHaveLength(25);
    expect(panel.getAttribute('style')).toBe(before);
    expect(rule('.shop-list')).toMatch(/overflow-y:\s*auto/);
    expect(rule('.shop-list')).toMatch(/flex:\s*1 1 auto/);
    expect(rule('.shop-list')).toMatch(/min-height:\s*0/);
    expect(rule('.shop')).toMatch(/height:\s*100%/);
  });
});
