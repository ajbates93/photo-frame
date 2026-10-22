import '../css/views/shopping.css';
import { fmtTime } from '../lib/time.js';
import { esc, setHtml } from '../ui/html.js';

const MAX_CHIPS = 8;

const SKELETON = `
<div class="shop">
  <div class="shop-head">
    <h2>Shopping</h2>
    <div class="shop-stale" hidden></div>
  </div>
  <div class="shop-add">
    <input type="text" class="shop-input" placeholder="Add an item" autocomplete="off" maxlength="120" aria-label="New item">
    <button type="button" class="shop-btn" data-add>Add</button>
  </div>
  <div class="shop-chips"></div>
  <div class="shop-list"></div>
</div>`;

// Text of checked items, de-duplicated case-insensitively, at most eight.
export function quickAddChips(items) {
  const seen = new Set();
  const out = [];
  for (const it of items) {
    if (!it.checked) continue;
    const text = String(it.text == null ? '' : it.text).trim();
    const key = text.toLowerCase();
    if (!text || seen.has(key)) continue;
    seen.add(key);
    out.push(text);
    if (out.length === MAX_CHIPS) break;
  }
  return out;
}

function rowHtml(it) {
  return `<button type="button" class="shop-item${it.checked ? ' is-checked' : ''}" data-iid="${esc(it.id)}" data-checked="${it.checked ? '1' : '0'}">`
    + `<span class="shop-box"></span><span class="shop-text">${esc(it.text)}</span></button>`;
}

export function createShoppingView() {
  let q = null;
  let ctx = null;
  let state = null;

  const $ = (sel) => q.querySelector(sel);

  function render() {
    if (!state || !q) return;
    const shopping = state.shopping || { items: [], syncedAt: null, stale: false };
    const items = shopping.items || [];
    const open = items.filter((i) => !i.checked);
    const done = items.filter((i) => i.checked);

    const stale = $('.shop-stale');
    if (shopping.stale) {
      const t = shopping.syncedAt ? new Date(shopping.syncedAt) : null;
      const when = t && !Number.isNaN(t.getTime()) ? ` · last synced ${fmtTime(t)}` : '';
      stale.textContent = `Out of sync with Keep${when}`;
      stale.hidden = false;
    } else {
      stale.textContent = '';
      stale.hidden = true;
    }

    setHtml($('.shop-chips'), quickAddChips(items)
      .map((t) => `<button type="button" class="shop-chip" data-chip="${esc(t)}">${esc(t)}</button>`).join(''));

    let html = open.map(rowHtml).join('');
    if (!open.length && !done.length) html = '<div class="shop-empty">Nothing on the list</div>';
    if (done.length) html += `<div class="shop-sub">Done</div>${done.map(rowHtml).join('')}`;
    setHtml($('.shop-list'), html);
  }

  async function addText(text) {
    const t = String(text).trim();
    if (!t) return;
    await ctx.act('POST', '/api/shopping/items', { text: t });
  }

  async function submit() {
    const input = $('.shop-input');
    const t = input.value.trim();
    if (!t) return;
    await addText(t);
    input.value = '';
  }

  function onClick(e) {
    const t = e.target;
    if (t.closest('[data-add]')) { submit(); return; }
    const chip = t.closest('[data-chip]');
    if (chip) { addText(chip.dataset.chip); return; }
    const row = t.closest('[data-iid]');
    if (row) {
      ctx.act('PATCH', `/api/shopping/items/${encodeURIComponent(row.dataset.iid)}`,
        { checked: row.dataset.checked !== '1' });
    }
  }

  function onKey(e) {
    if (e.key === 'Enter' && e.target.closest('.shop-input')) submit();
  }

  return {
    mount(el, c) {
      ctx = c;
      el.innerHTML = SKELETON;
      q = el;
      el.addEventListener('click', onClick);
      el.addEventListener('keydown', onKey);
    },

    update(s, c) {
      ctx = c;
      state = s;
      render();
    },
  };
}
