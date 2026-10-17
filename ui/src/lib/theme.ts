// Theme application: the one place that turns Appearance settings into attributes and
// custom properties on <html>. Onboarding previews, Settings and boot all go through it,
// so a preview is exactly what the saved setting will look like.
//
// Names and hints are getters, so whatever reads them gets the interface language.
import { accentTokens, parseColor, type RGB } from './color';
import { ACCENTS as ACCENT_PRESETS, DEFAULT_ACCENT } from './accents';
import { t, type Key } from './i18n/index.svelte';
export { DEFAULT_ACCENT } from './accents';

export type ThemeId = 'dark' | 'oled' | 'light';

export const THEMES: { id: ThemeId; label: string; hint: string }[] = [
	{
		id: 'dark',
		get label() {
			return t('settings.themeDark');
		},
		get hint() {
			return t('settings.themeDarkHint');
		}
	},
	{
		id: 'oled',
		get label() {
			return t('settings.themeOled');
		},
		get hint() {
			return t('settings.themeOledHint');
		}
	},
	{
		id: 'light',
		get label() {
			return t('settings.themeLight');
		},
		get hint() {
			return t('settings.themeLightHint');
		}
	}
];

export const WELL_STYLES = [
	{
		id: 'tide',
		get label() {
			return t('settings.wellTide');
		},
		get hint() {
			return t('settings.wellTideHint');
		}
	},
	{
		id: 'aurora',
		get label() {
			return t('settings.wellAurora');
		},
		get hint() {
			return t('settings.wellAuroraHint');
		}
	},
	{
		id: 'ember',
		get label() {
			return t('settings.wellEmber');
		},
		get hint() {
			return t('settings.wellEmberHint');
		}
	},
	{
		id: 'mono',
		get label() {
			return t('settings.wellMono');
		},
		get hint() {
			return t('settings.wellMonoHint');
		}
	}
] as const;

/** Each preset's message, by its English name in accents.ts. */
const ACCENT_NAMES = {
	Lagoon: 'settings.accentLagoon',
	Glacier: 'settings.accentGlacier',
	Lupine: 'settings.accentLupine',
	Fireweed: 'settings.accentFireweed',
	Amber: 'settings.accentAmber',
	Moss: 'settings.accentMoss',
	Lichen: 'settings.accentLichen',
	Sunrise: 'settings.accentSunrise'
} as const satisfies Record<(typeof ACCENT_PRESETS)[number]['name'], Key>;

/** The accent presets with names in the interface language (what screen readers announce). */
export const ACCENTS = ACCENT_PRESETS.map((a) => ({
	hex: a.hex,
	get name() {
		return t(ACCENT_NAMES[a.name]);
	}
}));

export const accentName = (hex: string) => ACCENTS.find((a) => a.hex.toLowerCase() === hex?.toLowerCase())?.name ?? t('settings.customColorHex', { hex });

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
