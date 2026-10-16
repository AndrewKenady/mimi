// Accent presets: the single list used by onboarding, Settings, the style guide and the
// contrast audit. Names are what screen readers announce. No imports, so Node scripts
// can load this file directly.
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

export const accentName = (hex: string) => ACCENTS.find((a) => a.hex.toLowerCase() === hex?.toLowerCase())?.name ?? `Custom colour ${hex}`;
