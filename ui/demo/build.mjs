// npm run build:demo: the browser demo for GitHub Pages, in build-demo/ (see src/lib/demo).
//
//   MIMI_DEMO=1 vite build   the app with the recorded Core, served under /mimi/demo
//   + demo/maps/             a small real map (Old Faithful to Jackson): tiles, fonts, sprites
//
// MIMI_DEMO_BASE overrides the base path (default /mimi/demo).
import { spawnSync } from 'node:child_process';
import { cpSync, existsSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ui = join(dirname(fileURLToPath(import.meta.url)), '..');
const out = join(ui, 'build-demo');
const vite = join(ui, 'node_modules', 'vite', 'bin', 'vite.js');

const r = spawnSync(process.execPath, [vite, 'build'], { cwd: ui, stdio: 'inherit', env: { ...process.env, MIMI_DEMO: '1' } });
if (r.status !== 0) process.exit(r.status ?? 1);

const maps = join(ui, 'demo', 'maps');
if (existsSync(maps)) cpSync(maps, join(out, 'maps'), { recursive: true });

const size = (p) => (statSync(p).isDirectory() ? readdirSync(p).reduce((n, f) => n + size(join(p, f)), 0) : statSync(p).size);
console.log(`\nDemo: ${out} (${(size(out) / 1048576).toFixed(1)} MB)`);
