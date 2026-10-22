export const REQUEST_TIMEOUT_MS = 8000;

async function send(path, init) {
  const res = await fetch(path, init);
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON body */ }
  if (!res.ok) {
    throw new Error((data && data.error) || `Request failed (${res.status})`);
  }
  if (data === null || typeof data !== 'object') {
    throw new Error('Invalid response from server');
  }
  return data;
}

// A hung server must still fail: abort the fetch and reject after REQUEST_TIMEOUT_MS
// (the race also covers a fetch or body read that ignores the abort signal).
function request(method, path, body) {
  const ctl = new AbortController();
  const init = { method, headers: {}, signal: ctl.signal };
  if (body !== undefined) {
    init.headers['content-type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  let timer = null;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      ctl.abort();
      reject(new Error('Request timed out'));
    }, REQUEST_TIMEOUT_MS);
  });
  return Promise.race([send(path, init), timeout]).finally(() => clearTimeout(timer));
}

export const api = {
  getState(search = '') {
    return request('GET', `/api/state${search}`);
  },
  act(method, path, body) {
    return request(method, path, body);
  },
};
