export function createStore({ load, intervalMs = 15000 }) {
  let state = null;
  let stale = false;
  let error = null;
  let timer = null;
  let seq = 0;
  const subs = new Set();
  const snapshot = () => ({ state, stale, error });
  const notify = () => subs.forEach((fn) => fn(snapshot()));

  async function refresh() {
    const mine = seq;
    try {
      const next = await load();
      if (seq !== mine) return;
      if (next === null || typeof next !== 'object') throw new Error('Invalid state');
      state = next;
      stale = false;
      error = null;
    } catch (e) {
      if (seq !== mine) return;
      stale = true;
      error = (e && e.message) || String(e);
    }
    notify();
  }

  function startPolling() {
    if (timer === null) timer = setInterval(refresh, intervalMs);
  }
  function stopPolling() {
    if (timer !== null && subs.size === 0) {
      clearInterval(timer);
      timer = null;
    }
  }

  return {
    get: snapshot,
    subscribe(fn) {
      subs.add(fn);
      startPolling();
      return () => {
        subs.delete(fn);
        stopPolling();
      };
    },
    refresh,
    set(next) {
      seq += 1;
      state = next;
      stale = false;
      error = null;
      notify();
    },
  };
}
