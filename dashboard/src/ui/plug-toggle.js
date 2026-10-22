import { esc, setHtml } from './html.js';

const SHEET = `
<div class="sheet" hidden>
  <div class="sheet-back"></div>
  <div class="sheet-card" role="dialog" aria-modal="true">
    <h3 class="confirm-title"></h3>
    <div class="confirm-actions">
      <button type="button" class="confirm-btn sheet-close">Cancel</button>
      <button type="button" class="confirm-btn confirm-danger" data-confirm>Turn off</button>
    </div>
  </div>
</div>`;

const plugPath = (id) => `/api/plugs/${encodeURIComponent(id)}`;

// Plug switching shared by Control and the home strip: turning a confirm:true plug
// off asks first in a "Turn off X?" sheet appended to `host`.
export function createPlugToggle(host, getCtx) {
  host.insertAdjacentHTML('beforeend', SHEET);
  const sheet = host.lastElementChild;
  let pendingId = null;

  function close() {
    sheet.hidden = true;
    pendingId = null;
  }

  // Sheet taps never reach the host's own click handling (navigation, plug buttons).
  sheet.addEventListener('click', (e) => {
    e.stopPropagation();
    if (e.target.closest('[data-confirm]')) {
      const id = pendingId;
      close();
      if (id !== null) getCtx().act('POST', plugPath(id), { on: false });
      return;
    }
    if (e.target.closest('.sheet-close') || e.target.closest('.sheet-back')) close();
  });

  return {
    toggle(p) {
      if (!p || !p.reachable) return;
      if (p.on && p.confirm) {
        pendingId = p.id;
        setHtml(sheet.querySelector('.confirm-title'), `Turn off ${esc(p.name)}?`);
        sheet.hidden = false;
        return;
      }
      getCtx().act('POST', plugPath(p.id), { on: !p.on });
    },
    close,
  };
}
