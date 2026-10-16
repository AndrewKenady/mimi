#!/usr/bin/env node
// Contrast audit for the design tokens.
//
// Reads src/app.css, resolves every theme (Deep water, Midnight, Daylight) with and
// without high contrast, and checks each text token against each surface it can sit
// on, plus every accent preset through the same solver the app runs ($lib/color).
// Thresholds: WCAG AA 4.5:1 for text, 3:1 for UI indicators; 7:1 (AAA) for text in
// high-contrast mode. Exits non-zero on any failure, so `npm run check` enforces it.
//
//   node scripts/contrast.mjs            # summary + failures
//   node scripts/contrast.mjs --verbose  # every pair
//
// Requires Node >= 22.18 (imports TypeScript sources directly).
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { accentTokens, composite, contrast, inkOn, parseColor, tintOver } from '../src/lib/color.ts';
import { ACCENTS } from '../src/lib/accents.ts';

const css = readFileSync(fileURLToPath(new URL('../src/app.css', import.meta.url)), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const verbose = process.argv.includes('--verbose');

// --- tiny CSS reader: top-level rule blocks (skips @media/@theme bodies) --------------
function rules(src) {
	const out = [];
	let depth = 0;
	let start = 0;
	let selector = '';
	let atDepth = -1;
	for (let i = 0; i < src.length; i++) {
		const ch = src[i];
		if (ch === '{') {
			const sel = src.slice(start, i).trim();
			if (depth === 0 && sel.startsWith('@')) atDepth = 0;
			else if (atDepth < 0) selector = sel;
			depth++;
			start = i + 1;
		} else if (ch === '}') {
			depth--;
			if (atDepth < 0 && depth === 0 && selector) {
				const decls = {};
				for (const d of src.slice(start, i).split(';')) {
					const m = /^\s*(--[\w-]+)\s*:\s*([\s\S]+?)\s*$/.exec(d);
					if (m) decls[m[1]] = m[2];
				}
				out.push({ selector, decls, order: out.length });
				selector = '';
			}
			if (depth === 0) atDepth = -1;
			start = i + 1;
		}
	}
	return out;
}

/** Does a simple selector list (`:root, [data-theme='light'][data-contrast='high']`) apply to ctx? */
function match(selector, ctx) {
	let best = -1;
	for (const one of selector.split(',').map((s) => s.trim())) {
		const attrs = [...one.matchAll(/\[data-([\w-]+)(?:='([^']*)')?\]/g)];
		const rest = one.replace(/\[[^\]]*\]/g, '').replace(':root', '').trim();
		if (rest) continue; // a component selector, not a token block
		if (attrs.every(([, k, v]) => v === undefined || ctx[k] === v)) best = Math.max(best, attrs.length + (one.includes(':root') ? 1 : 0));
	}
	return best;
}

function resolve(ctx) {
	const applicable = rules(css)
		.map((r) => ({ ...r, spec: match(r.selector, ctx) }))
		.filter((r) => r.spec >= 0)
		.sort((a, b) => a.spec - b.spec || a.order - b.order);
	const vars = {};
	for (const r of applicable) Object.assign(vars, r.decls);
	return vars;
}

// --- what is checked ------------------------------------------------------------------
const SURFACES = ['--bg', '--bg-2', '--surface', '--surface-2', '--surface-3'];
const TEXT = ['--text', '--text-2', '--text-3', '--ok', '--warn', '--danger', '--accent-2'];
const THEMES = [
	{ name: 'Deep water', ctx: { theme: 'dark', contrast: 'normal' } },
	{ name: 'Midnight', ctx: { theme: 'oled', contrast: 'normal' } },
	{ name: 'Daylight', ctx: { theme: 'light', contrast: 'normal' } },
	{ name: 'Deep water · high contrast', ctx: { theme: 'dark', contrast: 'high' } },
	{ name: 'Midnight · high contrast', ctx: { theme: 'oled', contrast: 'high' } },
	{ name: 'Daylight · high contrast', ctx: { theme: 'light', contrast: 'high' } }
];
// Adversarial custom accents (the colour picker allows anything).
const CUSTOM = ['#333333', '#ffffff', '#00ff00', '#ff0000', '#1e3a8a'];

const rgb = (v, name) => {
	const c = parseColor(v ?? '');
	if (!c) throw new Error(`${name} is not a plain colour: ${v}`);
	return c;
};

let failures = 0;
let checks = 0;
const rows = [];
function check(theme, label, fg, bg, min) {
	checks++;
	const ratio = contrast(fg, bg);
	const ok = ratio >= min - 1e-9;
	if (!ok) failures++;
	if (!ok || verbose) rows.push(`${ok ? '  ok ' : 'FAIL '} ${theme.padEnd(28)} ${label.padEnd(44)} ${ratio.toFixed(2).padStart(5)} (min ${min})`);
	return ratio;
}

const summary = [];
for (const { name, ctx } of THEMES) {
	const v = resolve(ctx);
	const high = ctx.contrast === 'high';
	const minText = high ? 7 : 4.5;
	const bgs = SURFACES.map((s) => [s, rgb(v[s], s).slice(0, 3)]);
	bgs.push(['--glass', composite(rgb(v['--glass'], '--glass'), bgs[0][1])]);
	let worst = Infinity;
	for (const t of TEXT) {
		const fg = rgb(v[t], t);
		for (const [b, bg] of bgs) worst = Math.min(worst, check(name, `${t} on ${b}`, fg, bg, minText));
	}
	// Status colours on their own soft tints (error tags, warning lines).
	for (const [t, p] of [['--danger', 0.1], ['--warn', 0.12]]) {
		const c = rgb(v[t], t).slice(0, 3);
		for (const [b, bg] of bgs) check(name, `${t} on its tint over ${b}`, c, tintOver(c, p, bg), minText);
	}
	check(name, '--danger-ink on --danger', rgb(v['--danger-ink'], '--danger-ink'), rgb(v['--danger'], '--danger'), 4.5);

	// Accents: every preset and some hostile custom colours, through the app's solver.
	const surf = bgs.slice(0, 5).map(([, c]) => c);
	for (const hex of [...ACCENTS.map((a) => a.hex), ...CUSTOM]) {
		const { accent, ink } = accentTokens(hex, { light: ctx.theme === 'light', surfaces: surf, target: high ? 7 : 4.5 });
		const a = rgb(accent, 'accent').slice(0, 3);
		for (const [b, bg] of bgs.slice(0, 5)) {
			worst = Math.min(worst, check(name, `accent ${hex}→${accent} on ${b}`, a, bg, minText));
			check(name, `accent ${hex} on --accent-soft over ${b}`, a, tintOver(a, 0.16, bg), minText);
			check(name, `focus ring ${accent} vs ${b} (UI)`, a, bg, 3);
		}
		check(name, `--accent-ink ${ink} on accent ${accent}`, rgb(ink, 'ink'), a, 4.5);
	}
	summary.push(`  ${name.padEnd(28)} worst text pair ${worst.toFixed(2)}:1 (needs ${minText})`);
}

// Avatar initials sit on each person's colour; inkOn() picks the ink.
for (const hex of [...ACCENTS.map((a) => a.hex), ...CUSTOM]) check('Avatars', `initial on ${hex}`, rgb(inkOn(hex), 'ink'), rgb(hex, 'c'), 4.5);

console.log(`Mimi contrast audit — ${checks} pairs across ${THEMES.length} themes\n`);
console.log(summary.join('\n'));
if (rows.length) console.log('\n' + rows.join('\n'));
console.log(failures ? `\n${failures} pair(s) below threshold.` : '\nAll pairs pass.');
process.exit(failures ? 1 : 0);
