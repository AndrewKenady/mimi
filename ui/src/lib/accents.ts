// Accent presets: the single list used by onboarding, Settings, the style guide and the
// contrast audit. No imports, so Node scripts can load this file directly; that is also
// why the names here stay English. They are the presets' ids for translation: the
// interface takes ACCENTS and accentName from theme.ts, which name each preset in the
// interface language (what screen readers announce).
export const ACCENTS = [
	{ hex: '#6EE7D2', name: 'Lagoon' },
	{ hex: '#8AB4FF', name: 'Glacier' },
	{ hex: '#B69CFF', name: 'Lupine' },
	{ hex: '#F28FAD', name: 'Fireweed' },
	{ hex: '#F5B971', name: 'Amber' },
	{ hex: '#7DD3A8', name: 'Moss' },
	{ hex: '#F6E27A', name: 'Lichen' },
	{ hex: '#FF9E7A', name: 'Sunrise' }
] as const;

export const DEFAULT_ACCENT: string = ACCENTS[0].hex;

export const accentName = (hex: string) => ACCENTS.find((a) => a.hex.toLowerCase() === hex?.toLowerCase())?.name ?? `Custom color ${hex}`;
