async function request(method, path, body) {
  const init = { method, headers: {} };
  if (body !== undefined) {
    init.headers['content-type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
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

export const api = {
  getState(search = '') {
    return request('GET', `/api/state${search}`);
  },
  act(method, path, body) {
    return request(method, path, body);
  },
};
