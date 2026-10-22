export const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const HEX = /^#[0-9a-f]{6}$/i;

// A calendar colour is only trusted when it is a plain 6-digit hex; otherwise null.
export function validColor(c) {
  return typeof c === 'string' && HEX.test(c) ? c : null;
}

export function tint(hex, alpha) {
  const m = /^#([0-9a-f]{6})$/i.exec(hex || '');
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

// Assign innerHTML only when it changed, so repeated updates don't churn the DOM.
export function setHtml(el, html) {
  if (el.__html === html) return;
  el.__html = html;
  el.innerHTML = html;
}
