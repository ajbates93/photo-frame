// Shows one section at a time. Views are mounted by the caller; the router only
// toggles visibility and marks the matching rail button.
export function createRouter(root, views, { onGo } = {}) {
  let active = null;

  function go(name) {
    if (!(name in views)) return;
    active = name;
    root.querySelectorAll('[data-view]').forEach((el) => {
      el.classList.toggle('is-active', el.dataset.view === name);
    });
    root.querySelectorAll('[data-go]').forEach((el) => {
      const on = el.dataset.go === name;
      el.classList.toggle('is-active', on);
      if (on) el.setAttribute('aria-current', 'page');
      else el.removeAttribute('aria-current');
    });
    if (onGo) onGo(name);
  }

  return { go, current: () => active };
}
