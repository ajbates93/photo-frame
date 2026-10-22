// Dev-only font playground. Loaded from main.js only when import.meta.env.DEV,
// so none of these fonts or this panel reach the production build.
import '@fontsource-variable/fraunces/index.css';
import '@fontsource/young-serif/index.css';
import '@fontsource/dm-serif-display/index.css';
import '@fontsource-variable/newsreader/index.css';
import '@fontsource-variable/bricolage-grotesque/index.css';
import '@fontsource-variable/space-grotesk/index.css';
import '@fontsource-variable/outfit/index.css';
import '@fontsource-variable/inter/index.css';
import '@fontsource-variable/manrope/index.css';
import '@fontsource-variable/figtree/index.css';
import '@fontsource-variable/dm-sans/index.css';

const HEADINGS = [
  ['DM Serif Display (current)', "'DM Serif Display'"],
  ['Fraunces', "'Fraunces Variable'"],
  ['Young Serif', "'Young Serif'"],
  ['Newsreader', "'Newsreader Variable'"],
  ['Bricolage Grotesque', "'Bricolage Grotesque Variable'"],
  ['Space Grotesk', "'Space Grotesk Variable'"],
  ['Outfit', "'Outfit Variable'"],
];
const BODIES = [
  ['DM Sans (current)', "'DM Sans Variable'"],
  ['Inter', "'Inter Variable'"],
  ['Manrope', "'Manrope Variable'"],
  ['Figtree', "'Figtree Variable'"],
  ['Bricolage Grotesque', "'Bricolage Grotesque Variable'"],
  ['Outfit', "'Outfit Variable'"],
];
const KEY = 'dev-fonts';

function apply(display, sans) {
  const root = document.documentElement.style;
  root.setProperty('--display', `${display}, Georgia, serif`);
  root.setProperty('--sans', `${sans}, -apple-system, 'Helvetica Neue', Arial, sans-serif`);
}

function select(label, options, value, onChange) {
  const wrap = document.createElement('label');
  wrap.style.cssText = 'display:flex;flex-direction:column;gap:4px;font:600 11px/1.2 -apple-system,sans-serif;letter-spacing:.04em;text-transform:uppercase;color:#555';
  wrap.textContent = label;
  const s = document.createElement('select');
  s.style.cssText = 'font:14px -apple-system,sans-serif;padding:4px;text-transform:none;letter-spacing:0';
  options.forEach(([name, stack]) => {
    const o = document.createElement('option');
    o.value = stack;
    o.textContent = name;
    s.appendChild(o);
  });
  s.value = value;
  s.addEventListener('change', () => onChange(s.value));
  wrap.appendChild(s);
  return wrap;
}

export function mountFontPicker() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch { saved = {}; }
  let display = saved.display || HEADINGS[0][1];
  let sans = saved.sans || BODIES[0][1];
  apply(display, sans);

  const save = () => {
    apply(display, sans);
    try { localStorage.setItem(KEY, JSON.stringify({ display, sans })); } catch { /* ignore */ }
  };

  const panel = document.createElement('div');
  panel.style.cssText = 'position:fixed;right:12px;bottom:12px;z-index:9999;display:flex;gap:10px;align-items:flex-end;'
    + 'background:rgba(255,255,255,.96);color:#111;padding:10px 12px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,.25)';
  panel.appendChild(select('Headings & numbers', HEADINGS, display, (v) => { display = v; save(); }));
  panel.appendChild(select('Body text', BODIES, sans, (v) => { sans = v; save(); }));
  const hide = document.createElement('button');
  hide.textContent = '×';
  hide.title = 'Hide (reload to bring back)';
  hide.style.cssText = 'font:18px sans-serif;border:0;background:none;cursor:pointer;padding:0 2px';
  hide.addEventListener('click', () => panel.remove());
  panel.appendChild(hide);
  document.body.appendChild(panel);
}
