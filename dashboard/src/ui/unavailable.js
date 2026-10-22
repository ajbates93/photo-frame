import '../css/unavailable.css';

export const OFFLINE_MESSAGE = "Can't reach the home server — retrying";

// Centred message laid over a view or tile; idempotent.
export function showUnavailable(el, text = OFFLINE_MESSAGE) {
  let box = el.querySelector(':scope > .unavailable');
  if (!box) {
    box = el.ownerDocument.createElement('div');
    box.className = 'unavailable';
    el.appendChild(box);
  }
  box.textContent = text;
}

export function clearUnavailable(root) {
  root.querySelectorAll('.unavailable').forEach((b) => b.remove());
}
