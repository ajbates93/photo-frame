import { createMockApi } from '../dev/mock-api.js';
import { api } from '../src/api.js';

const NOW = new Date(2026, 9, 22, 8, 42);

describe('mock api', () => {
  it('serves the fixture state', () => {
    const r = createMockApi(NOW).handle({ method: 'GET', url: '/api/state' });
    expect(r.status).toBe(200);
    expect(r.json.events).toHaveLength(13);
    expect(r.json.photos).toHaveLength(8);
    expect(r.json.photos.filter((p) => p.takenAt === null && p.place === null)).toHaveLength(2);
    expect(r.json.shopping.items).toHaveLength(7);
    expect(r.json.shopping.items.filter((i) => i.checked)).toHaveLength(2);
    expect(r.json.plugs).toHaveLength(4);
  });

  it('?fail=1 returns 503 and ?nulls=1 nulls optional fields', () => {
    const m = createMockApi(NOW);
    const f = m.handle({ method: 'GET', url: '/api/state?fail=1' });
    expect(f.status).toBe(503);
    expect(typeof f.json.error).toBe('string');
    const n = m.handle({ method: 'GET', url: '/api/state?nulls=1' }).json;
    expect(n.weather).toBeNull();
    expect(n.speaker).toBeNull();
    expect(n.claude.usage).toBeNull();
  });

  it('?now=<ISO> regenerates fixtures relative to that time; plain requests keep mutations', () => {
    const m = createMockApi(NOW);
    const pinned = m.handle({ method: 'GET', url: '/api/state?now=2026-12-25T08:42:00%2B00:00' }).json;
    expect(pinned.events[0].start.startsWith('2026-12-25')).toBe(true);
    const plain = m.handle({ method: 'GET', url: '/api/state' }).json;
    expect(plain.events[0].start.startsWith('2026-10-22')).toBe(true);
    const bad = m.handle({ method: 'GET', url: '/api/state?now=nope' }).json;
    expect(bad.events[0].start.startsWith('2026-10-22')).toBe(true);
  });

  it('PATCH shopping item checks it', () => {
    const m = createMockApi(NOW);
    const r = m.handle({ method: 'PATCH', url: '/api/shopping/items/s1', body: { checked: true } });
    expect(r.status).toBe(200);
    expect(r.json.shopping.items.find((i) => i.id === 's1').checked).toBe(true);
  });

  it('POST /api/tasks adds a task; unknown task id is 404', () => {
    const m = createMockApi(NOW);
    const r = m.handle({ method: 'POST', url: '/api/tasks', body: { title: 'New one', assignee: 'any', due: null } });
    expect(r.json.tasks).toHaveLength(4);
    expect(r.json.tasks.at(-1).title).toBe('New one');
    const bad = m.handle({ method: 'PATCH', url: '/api/tasks/nope', body: { done: true } });
    expect(bad.status).toBe(404);
    expect(typeof bad.json.error).toBe('string');
  });

  it('serves a distinct SVG gradient per photo id', () => {
    const m = createMockApi(NOW);
    const a = m.handle({ method: 'GET', url: '/api/photos/p1' });
    const b = m.handle({ method: 'GET', url: '/api/photos/p2' });
    expect(a.headers['content-type']).toBe('image/svg+xml');
    expect(a.json).toContain('viewBox="0 0 1280 800"');
    expect(a.json).not.toBe(b.json);
  });
});

describe('mock api validation', () => {
  const m = () => createMockApi(NOW);
  const cases = [
    ['PATCH', '/api/shopping/items/s1', {}],
    ['PATCH', '/api/shopping/items/s1', { checked: 'yes' }],
    ['PATCH', '/api/tasks/t1', {}],
    ['POST', '/api/plugs/pl1', {}],
    ['POST', '/api/tasks', { title: 'x', assignee: 'bob', due: null }],
    ['POST', '/api/tasks', { title: 'x', assignee: 'any', due: 5 }],
    ['POST', '/api/tasks', { title: 'x', assignee: 'any', due: 'not a date' }],
  ];
  it.each(cases)('%s %s %j returns 400 with error', (method, url, body) => {
    const r = m().handle({ method, url, body });
    expect(r.status).toBe(400);
    expect(typeof r.json.error).toBe('string');
  });

  it('malformed JSON and bad URL encoding return 400 without throwing', () => {
    expect(m().handle({ method: 'POST', url: '/api/tasks', badJson: true }).status).toBe(400);
    expect(m().handle({ method: 'GET', url: '/api/photos/%E0%A4%A' }).status).toBe(400);
  });
});

describe('api client', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('act rejects with the server error message on non-2xx', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404, json: async () => ({ error: 'Task not found' }) })));
    await expect(api.act('PATCH', '/api/tasks/x', { done: true })).rejects.toThrow('Task not found');
  });

  it('act rejects on a 2xx with a missing or unparseable body', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => { throw new Error('bad'); } })));
    await expect(api.act('POST', '/api/screen/wake')).rejects.toThrow('Invalid response');
  });

  it('act sends JSON and resolves with the state', async () => {
    const f = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ generatedAt: 'z' }) }));
    vi.stubGlobal('fetch', f);
    await expect(api.act('POST', '/api/tasks', { title: 't' })).resolves.toEqual({ generatedAt: 'z' });
    expect(f).toHaveBeenCalledWith('/api/tasks', expect.objectContaining({ method: 'POST', body: '{"title":"t"}' }));
  });
});
