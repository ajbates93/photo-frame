// Fails the build if CSS uses features the Android 6 / WebView 106 target cannot render.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const RULES = [
  [/#[0-9a-f]{4}\b|#[0-9a-f]{8}\b/gi, '4- or 8-digit hex colour'],
  [/color-mix\(/gi, 'color-mix()'],
  [/oklch\(/gi, 'oklch()'],
  [/\d(?:d|s|l)vh\b/gi, 'dvh/svh/lvh unit'],
  [/(?:^|[{};,])\s*&/g, 'nested & selector'],
];

export function findViolations(cssText) {
  const out = [];
  for (const [re, label] of RULES) {
    for (const m of cssText.matchAll(re)) out.push(`${label}: ${m[0].trim()}`);
  }
  return out;
}

function cssFiles(dir) {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return cssFiles(p);
    return p.endsWith('.css') ? [p] : [];
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const dir = process.argv[2];
  if (!dir) {
    console.error('usage: check-compat.mjs <dir>');
    process.exit(2);
  }
  let total = 0;
  for (const file of cssFiles(dir)) {
    for (const v of findViolations(readFileSync(file, 'utf8'))) {
      console.error(`${file}: ${v}`);
      total++;
    }
  }
  console.log(`check-compat: ${total} violations`);
  process.exit(total ? 1 : 0);
}
