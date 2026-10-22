// Visual review: starts the Vite dev server, then takes 1280x800 headless-Chrome screenshots
// of every view in both themes (theme follows the pinned ?now) plus the nulls/fail states.
import { spawn, spawnSync } from 'node:child_process';
import { createServer } from 'node:net';
import { mkdirSync, mkdtempSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const out = join(root, 'screenshots');
const CHROME = process.env.CHROME_BIN || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const VIEWS = ['home', 'calendar', 'tasks', 'shopping', 'photos', 'control', 'claude'];
const NOW = { paper: '2026-10-22T08:42:00+01:00', night: '2026-10-22T20:15:00+01:00' };
const env = { ...process.env, TZ: 'Europe/London' };

function freePort() {
  return new Promise((resolve, reject) => {
    const s = createServer();
    s.once('error', reject);
    s.listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => resolve(port)); });
  });
}

async function waitFor(url, tries = 100) {
  for (let i = 0; i < tries; i++) {
    try { if ((await fetch(url)).ok) return; } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`Dev server did not respond at ${url}`);
}

function shots() {
  const list = [];
  for (const theme of ['paper', 'night']) {
    for (const v of VIEWS) list.push([`${v}-${theme}`, `?view=${v}&now=${encodeURIComponent(NOW[theme])}`]);
  }
  const day = encodeURIComponent(NOW.paper);
  list.push(['home-nulls', `?nulls=1&now=${day}`]);
  list.push(['home-fail', `?fail=1&now=${day}`]);
  return list;
}

const port = await freePort();
const vite = spawn(process.execPath, [join(root, 'node_modules/vite/bin/vite.js'), '--port', String(port), '--strictPort', '--host', '127.0.0.1'],
  { cwd: root, env, stdio: 'ignore' });
const profile = mkdtempSync(join(tmpdir(), 'pf-shots-'));
let failed = 0;

try {
  if (!existsSync(CHROME)) throw new Error(`Chrome not found at ${CHROME} (set CHROME_BIN)`);
  const base = `http://127.0.0.1:${port}/`;
  await waitFor(base);
  mkdirSync(out, { recursive: true });
  for (const [name, query] of shots()) {
    const file = join(out, `${name}.png`);
    const r = spawnSync(CHROME, [
      '--headless=new', '--hide-scrollbars', '--no-first-run',
      `--user-data-dir=${profile}`, '--window-size=1280,800', `--virtual-time-budget=${name.startsWith('photos') ? 4800 : 4000}`,
      `--screenshot=${file}`, `${base}${query}`,
    ], { env, stdio: 'ignore', timeout: 60000 });
    if (r.status !== 0 || !existsSync(file)) { failed++; console.error(`FAILED ${name}`); } else console.log(`ok ${name}.png`);
  }
} catch (e) {
  console.error(e.message);
  failed++;
} finally {
  vite.kill();
  rmSync(profile, { recursive: true, force: true });
}
process.exit(failed ? 1 : 0);
