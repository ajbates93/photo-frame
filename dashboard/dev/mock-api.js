import { makeFixtureState } from './fixtures.js';

const PAIRS = [
  ['#2b5876', '#4e4376'], ['#f2994a', '#f2c94c'], ['#11998e', '#38ef7d'], ['#cb2d3e', '#ef473a'],
  ['#4568dc', '#b06ab3'], ['#134e5e', '#71b280'], ['#614385', '#516395'], ['#e96443', '#904e95'],
];

function photoSvg(id) {
  let h = 0;
  for (const ch of String(id)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const [a, b] = PAIRS[h % PAIRS.length];
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 800" width="1280" height="800">` +
    `<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${a}"/>` +
    `<stop offset="1" stop-color="${b}"/></linearGradient></defs>` +
    `<rect width="1280" height="800" fill="url(#g)"/></svg>`;
}

export function createMockApi(now) {
  const state = makeFixtureState(now);
  let nextId = 100;
  const err = (status, message) => ({ status, json: { error: message } });
  const ok = () => {
    state.generatedAt = new Date().toISOString();
    return { status: 200, json: structuredClone(state) };
  };

  function handle({ method, url, body, badJson }) {
    if (badJson) return err(400, 'Malformed JSON');
    let u;
    try {
      u = new URL(url, 'http://localhost');
      decodeURIComponent(u.pathname);
    } catch {
      return err(400, 'Bad request URL');
    }
    const path = u.pathname;
    const q = u.searchParams;
    if (body === null || typeof body !== 'object') body = {};

    let m = path.match(/^\/api\/photos\/([^/]+)$/);
    if (m && method === 'GET') {
      return { status: 200, json: photoSvg(decodeURIComponent(m[1])), headers: { 'content-type': 'image/svg+xml' } };
    }

    if (path === '/api/state' && method === 'GET') {
      if (q.get('fail') === '1') return err(503, 'Service unavailable');
      // ?now=<ISO> regenerates the fixtures relative to that instant (screenshots).
      const pinned = q.get('now') ? new Date(q.get('now')) : null;
      const s = pinned && !Number.isNaN(pinned.getTime()) ? makeFixtureState(pinned) : structuredClone(state);
      if (q.get('nulls') === '1') {
        s.weather = null;
        s.speaker = null;
        s.claude.usage = null;
      }
      return { status: 200, json: s };
    }

    if (path === '/api/shopping/items' && method === 'POST') {
      if (typeof body.text !== 'string' || !body.text) return err(400, 'text required');
      if (body.text.length > 200) return err(400, 'text must be at most 200 characters');
      state.shopping.items.push({ id: `s${nextId++}`, text: body.text, checked: false });
      return ok();
    }
    if ((m = path.match(/^\/api\/shopping\/items\/([^/]+)$/)) && method === 'PATCH') {
      const item = state.shopping.items.find((i) => i.id === m[1]);
      if (!item) return err(404, 'Item not found');
      if (typeof body.checked !== 'boolean') return err(400, 'checked must be a boolean');
      item.checked = body.checked;
      return ok();
    }
    if (path === '/api/tasks' && method === 'POST') {
      if (typeof body.title !== 'string' || !body.title) return err(400, 'title required');
      if (!['alex', 'vicky', 'any'].includes(body.assignee)) return err(400, 'assignee must be alex, vicky or any');
      const due = body.due === undefined ? null : body.due;
      if (due !== null && (typeof due !== 'string' || Number.isNaN(Date.parse(due)))) {
        return err(400, 'due must be an ISO string or null');
      }
      state.tasks.push({
        id: `t${nextId++}`,
        title: body.title,
        assignee: body.assignee,
        due,
        done: false,
      });
      return ok();
    }
    if ((m = path.match(/^\/api\/tasks\/([^/]+)$/)) && (method === 'PATCH' || method === 'DELETE')) {
      const idx = state.tasks.findIndex((t) => t.id === m[1]);
      if (idx < 0) return err(404, 'Task not found');
      if (method === 'DELETE') state.tasks.splice(idx, 1);
      else if (typeof body.done !== 'boolean') return err(400, 'done must be a boolean');
      else state.tasks[idx].done = body.done;
      return ok();
    }
    if ((m = path.match(/^\/api\/plugs\/([^/]+)$/)) && method === 'POST') {
      const plug = state.plugs.find((p) => p.id === m[1]);
      if (!plug) return err(404, 'Plug not found');
      if (typeof body.on !== 'boolean') return err(400, 'on must be a boolean');
      plug.on = body.on;
      return ok();
    }
    if (path === '/api/speaker' && method === 'POST') {
      if (!state.speaker) return err(404, 'No speaker');
      if (body.action === 'play') state.speaker.playing = true;
      else if (body.action === 'pause') state.speaker.playing = false;
      else if (body.action === 'volume' && typeof body.volume === 'number') {
        state.speaker.volume = Math.max(0, Math.min(100, Math.round(body.volume)));
      } else return err(400, 'Invalid speaker action');
      return ok();
    }
    if (path === '/api/screen/wake' && method === 'POST') {
      state.screen.mode = 'on';
      return ok();
    }
    return err(404, 'Not found');
  }

  return { handle };
}

export function mockApi() {
  return {
    name: 'photo-frame-mock-api',
    apply: 'serve',
    configureServer(server) {
      const api = createMockApi(new Date());
      server.middlewares.use((req, res, next) => {
        if (!req.url || !req.url.startsWith('/api/')) return next();
        const chunks = [];
        req.on('data', (c) => chunks.push(c));
        req.on('end', () => {
          let body;
          let badJson = false;
          const raw = Buffer.concat(chunks).toString('utf8');
          if (raw) {
            try { body = JSON.parse(raw); } catch { badJson = true; }
          }
          let out;
          try {
            out = api.handle({ method: req.method, url: req.url, body, badJson });
          } catch (e) {
            out = { status: 500, json: { error: (e && e.message) || 'Internal error' } };
          }
          const headers = out.headers || { 'content-type': 'application/json' };
          res.statusCode = out.status;
          for (const [k, v] of Object.entries(headers)) res.setHeader(k, v);
          res.end(typeof out.json === 'string' ? out.json : JSON.stringify(out.json));
        });
      });
    },
  };
}
