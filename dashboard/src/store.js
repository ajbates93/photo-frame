export function createStore({ load, intervalMs = 15000 }) {
  let state = null;
  let stale = false;
  let error = null;
  let timer = null;
  let seq = 0;
  let inFlight = 0;
  const subs = new Set();
  const snapshot = () => ({ state, stale, error });
  // One throwing subscriber must not stop the others.
  const notify = () => subs.forEach((fn) => {
    try { fn(snapshot()); } catch (e) { console.error(e); }
  });

  async function refresh() {
    const mine = seq;
    inFlight += 1;
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
    } finally {
      inFlight -= 1;
    }
    notify();
  }

  // Interval ticks never pile up behind a slow load.
  function poll() {
    if (inFlight === 0) refresh();
  }

  function startPolling() {
    if (timer === null) timer = setInterval(poll, intervalMs);
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
