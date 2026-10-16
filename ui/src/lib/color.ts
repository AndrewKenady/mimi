// Colour maths for the design system: WCAG contrast, OKLab mixing, and the
// "make this colour readable here" solver used for user-chosen accents.
// Pure functions with no DOM access, so the contrast audit (scripts/contrast.mjs)
// runs exactly the code the app runs.

export type RGB = [number, number, number]; // 0..255
export type RGBA = [number, number, number, number]; // alpha 0..1

const clamp = (v: number, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));

/** Parse #rgb, #rrggbb, #rrggbbaa, rgb() or rgba(). Returns null for anything else. */
export function parseColor(input: string): RGBA | null {
	const s = input.trim().toLowerCase();
	let m = /^#([0-9a-f]{3})$/.exec(s);
	if (m) return [...m[1].split('').map((c) => parseInt(c + c, 16)), 1] as RGBA;
	m = /^#([0-9a-f]{6})([0-9a-f]{2})?$/.exec(s);
	if (m) {
		const n = parseInt(m[1], 16);
		return [(n >> 16) & 255, (n >> 8) & 255, n & 255, m[2] ? parseInt(m[2], 16) / 255 : 1];
	}
	m = /^rgba?\(([^)]+)\)$/.exec(s);
	if (m) {
		const p = m[1].split(/[\s,/]+/).filter(Boolean).map(Number);
		if (p.length >= 3 && p.slice(0, 3).every((x) => !Number.isNaN(x))) return [p[0], p[1], p[2], p[3] ?? 1];
	}
	return null;
}

export const toHex = (c: RGB | RGBA) =>
	'#' +
	c
		.slice(0, 3)
		.map((v) => Math.round(clamp(v, 0, 255)).toString(16).padStart(2, '0'))
		.join('');

/** Paint a translucent colour over an opaque one. */
export function composite(fg: RGBA, bg: RGB | RGBA): RGB {
	const a = fg[3];
	return [0, 1, 2].map((i) => fg[i] * a + bg[i] * (1 - a)) as RGB;
}

const lin = (c: number) => {
	c /= 255;
	return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
};
const unlin = (c: number) => 255 * (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);

/** WCAG 2.x relative luminance. */
export function luminance(c: RGB | RGBA): number {
	return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
}

/** WCAG contrast ratio, 1..21. */
export function contrast(a: RGB | RGBA, b: RGB | RGBA): number {
	const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
	return (x + 0.05) / (y + 0.05);
}

// --- OKLab, so mixes match CSS `color-mix(in oklab, …)` ----------------------
function toOklab(c: RGB): RGB {
	const [r, g, b] = c.map(lin);
	const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
	const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
	const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
	return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s, 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}
function fromOklab([L, A, B]: RGB): RGB {
	const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3;
	const m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3;
	const s = (L - 0.0894841775 * A - 1.291485548 * B) ** 3;
	return [
		unlin(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
		unlin(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
		unlin(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s)
	].map((v) => clamp(v, 0, 255)) as RGB;
}

/** `color-mix(in oklab, a p%, b)` for opaque colours. */
export function mixOklab(a: RGB, b: RGB, p: number): RGB {
	const x = toOklab(a);
	const y = toOklab(b);
	return fromOklab([0, 1, 2].map((i) => x[i] * p + y[i] * (1 - p)) as RGB);
}

/** `color-mix(in oklab, c p%, transparent)` painted over an opaque background. */
export function tintOver(c: RGB, p: number, bg: RGB): RGB {
	return composite([...c, p] as RGBA, bg);
}

/** Lighten (amount > 0) or darken (amount < 0) toward white/black in sRGB. */
export function shade(hex: string, amount: number): string {
	const c = parseColor(hex);
	if (!c) return hex;
	const t = amount < 0 ? 0 : 255;
	return toHex(c.slice(0, 3).map((v) => v + (t - v) * Math.abs(amount)) as RGB);
}

/** Move a colour's OKLab lightness by `dL` (-1..1), keeping hue and chroma (clipped to sRGB). */
export function shiftLightness(hex: string, dL: number): string {
	const c = parseColor(hex);
	if (!c) return hex;
	const [L, A, B] = toOklab(c.slice(0, 3) as RGB);
	return toHex(fromOklab([clamp(L + dL), A, B]));
}

/**
 * Nudge `hex` darker or lighter until it reaches `target` contrast against every colour in
 * `against`. Only OKLab lightness moves (1% steps), so hue and chroma survive: the result is
 * the closest readable relative of the original, not a muddy shade of it.
 */
export function readable(hex: string, against: RGB[] | ((candidate: RGB) => RGB[]), target: number, toward: 'dark' | 'light'): string {
	const worst = (h: string) => {
		const c = parseColor(h)!.slice(0, 3) as RGB;
		return Math.min(...(typeof against === 'function' ? against(c) : against).map((bg) => contrast(c, bg)));
	};
	for (let i = 0; i <= 100; i++) {
		const h = shiftLightness(hex, (toward === 'dark' ? -1 : 1) * i * 0.01);
		if (worst(h) >= target) return h;
	}
	return toward === 'dark' ? '#000000' : '#ffffff';
}

/** Text colour for a filled swatch: a deep shade of the same hue, or white when that can't reach AA. */
export function inkOn(hex: string, target = 4.5): string {
	const c = parseColor(hex);
	if (!c) return '#ffffff';
	const deep = toHex(mixOklab(c.slice(0, 3) as RGB, [0, 0, 0], 0.2));
	return contrast(parseColor(deep)!, c) >= target ? deep : '#ffffff';
}

/** Accent tokens for a theme, derived from the user's raw accent. See docs/DESIGN_SYSTEM.md → Accent. */
export function accentTokens(raw: string, opts: { light: boolean; surfaces: RGB[]; target: number }): { accent: string; ink: string } {
	const base = parseColor(raw) ? raw : '#6ee7d2';
	// Accent is used as text on every surface and on its own 16% tint (--accent-soft), so check both.
	const against = (c: RGB) => [...opts.surfaces, ...opts.surfaces.map((s) => tintOver(c, 0.16, s))];
	const accent = readable(base, against, opts.target, opts.light ? 'dark' : 'light');
	return { accent, ink: inkOn(accent, Math.min(opts.target, 7)) };
}
