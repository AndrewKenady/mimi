// Theme application: the one place that turns Appearance settings into attributes and
// custom properties on <html>. Onboarding previews, Settings and boot all go through it,
// so a preview is exactly what the saved setting will look like.
import { accentTokens, parseColor, type RGB } from './color';
import { DEFAULT_ACCENT } from './accents';
export { ACCENTS, DEFAULT_ACCENT, accentName } from './accents';

export type ThemeId = 'dark' | 'oled' | 'light';

export const THEMES: { id: ThemeId; label: string; hint: string }[] = [
	{ id: 'dark', label: 'Deep water', hint: 'Dark blue-black. The default.' },
	{ id: 'oled', label: 'Midnight', hint: 'True black for OLED screens and night use.' },
	{ id: 'light', label: 'Daylight', hint: 'Bright, for sunlight and well-lit rooms.' }
];

export const WELL_STYLES = [
	{ id: 'tide', label: 'Tide', hint: 'Your accent over deep teal water.' },
	{ id: 'aurora', label: 'Aurora', hint: 'Your accent over violet depths.' },
	{ id: 'ember', label: 'Ember', hint: 'Warm firelight, whatever the accent.' },
	{ id: 'mono', label: 'Mono', hint: 'Quiet grays. Least distracting.' }
] as const;

export type Appearance = {
	theme?: string;
	accent?: string;
	high_contrast?: boolean;
	reduced_motion?: boolean;
	density?: string;
	reading_font?: string;
	well_style?: string;
	font_scale?: number;
};

const BOOT_KEY = 'mimi.boot';

export function resolveTheme(pref: string | undefined): ThemeId {
	if (pref === 'auto') return matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
	return pref === 'light' || pref === 'oled' ? pref : 'dark';
}

const SURFACES = ['--bg', '--bg-2', '--surface', '--surface-2', '--surface-3'];

/** Apply appearance to <html>. Pass only what changed; the rest stays as it is. */
export function applyTheme(a: Appearance, root: HTMLElement = document.documentElement) {
	const theme = resolveTheme(a.theme ?? root.dataset.themePref);
	if (a.theme) root.dataset.themePref = a.theme;
	root.dataset.theme = theme;
	if (a.high_contrast !== undefined) root.dataset.contrast = a.high_contrast ? 'high' : 'normal';
	if (a.reduced_motion !== undefined) root.dataset.motion = a.reduced_motion ? 'reduced' : 'full';
	if (a.density) root.dataset.density = a.density;
	if (a.reading_font) root.dataset.reading = a.reading_font;
	if (a.well_style) root.dataset.well = a.well_style;
	if (a.font_scale) root.style.setProperty('--font-scale', String(a.font_scale));

	// The accent is the user's color, adjusted (lightness only) until it is readable as
	// text on every surface of this theme: AA normally, AAA with high contrast.
	const raw = a.accent || root.style.getPropertyValue('--accent-raw') || DEFAULT_ACCENT;
	root.style.removeProperty('--accent');
	root.style.removeProperty('--accent-ink');
	const cs = getComputedStyle(root);
	const surfaces = SURFACES.map((v) => parseColor(cs.getPropertyValue(v))?.slice(0, 3) as RGB).filter(Boolean);
	const { accent, ink } = accentTokens(raw, { light: theme === 'light', surfaces, target: root.dataset.contrast === 'high' ? 7 : 4.5 });
	root.style.setProperty('--accent-raw', raw);
	root.style.setProperty('--accent', accent);
	root.style.setProperty('--accent-ink', ink);

	const bg = cs.getPropertyValue('--bg').trim();
	document.querySelector('meta[name="theme-color"]')?.setAttribute('content', bg);
	saveBoot(root, bg);
}

/** Remember the look so the next launch paints it before any script or stylesheet loads (see app.html). */
function saveBoot(root: HTMLElement, bg: string) {
	const cs = getComputedStyle(root);
	const v = (p: string) => cs.getPropertyValue(p).trim();
	const snap = {
		pref: root.dataset.themePref,
		theme: root.dataset.theme,
		contrast: root.dataset.contrast,
		motion: root.dataset.motion,
		density: root.dataset.density,
		well: root.dataset.well,
		reading: root.dataset.reading,
		scale: root.style.getPropertyValue('--font-scale'),
		raw: root.style.getPropertyValue('--accent-raw'),
		accent: root.style.getPropertyValue('--accent'),
		ink: root.style.getPropertyValue('--accent-ink'),
		bg,
		text: v('--text'),
		wa: v('--well-a'),
		wb: v('--well-b'),
		wc: v('--well-c')
	};
	try {
		localStorage.setItem(BOOT_KEY, JSON.stringify(snap));
	} catch {
		/* private mode: boot falls back to the default look */
	}
}
