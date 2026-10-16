// Settings information architecture: the single source of truth for Settings' sections,
// their sub-sections (anchors within a page), who sees them, and the words people search
// for. The Settings page renders from this list and the command palette can consume it.
//
// Nine sections, down from thirteen: on a handheld every extra tab is another stop on
// the D-pad. Related pages were merged (General + Power → Device; Assistant + Voice →
// Assistant; Models + Library + Tools → Intelligence). Old URLs keep working through
// SETTINGS_REDIRECTS (e.g. /settings/models → /settings/intelligence#models).
import { SlidersHorizontal, Palette, Sparkles, Cpu, MapPin, Share2, Users, Gamepad2, HardDrive } from '@lucide/svelte';

export type SettingsSub = { id: string; label: string; keywords: string };
export type SettingsSection = {
	id: string;
	label: string;
	/** One line under the title; also shown in search results. */
	summary: string;
	icon: typeof Sparkles;
	/** Only the device owner sees (and can change) this section. */
	ownerOnly: boolean;
	keywords: string;
	subsections: SettingsSub[];
};

export const SETTINGS_SECTIONS: SettingsSection[] = [
	{
		id: 'device',
		label: 'Device',
		summary: 'Startup, full screen, PIN lock, units, battery.',
		icon: SlidersHorizontal,
		ownerOnly: true,
		keywords: 'general startup launch full screen kiosk units metric imperial clock time pin lock',
		subsections: [
			{ id: 'startup', label: 'Startup & window', keywords: 'launch startup full screen kiosk close' },
			{ id: 'regional', label: 'Lock & units', keywords: 'pin lock units metric imperial clock' },
			{ id: 'power', label: 'Power', keywords: 'battery saver power awake sleep' }
		]
	},
	{
		id: 'appearance',
		label: 'Appearance',
		summary: 'Theme, accent, the Well, text size, motion.',
		icon: Palette,
		ownerOnly: false,
		keywords: 'theme dark light oled midnight daylight accent colour color font text size density compact motion contrast well widgets home',
		subsections: [
			{ id: 'look', label: 'Look', keywords: 'theme accent well' },
			{ id: 'reading', label: 'Text & layout', keywords: 'font text size density reading serif' },
			{ id: 'accessibility', label: 'Comfort', keywords: 'motion contrast accessibility' },
			{ id: 'home', label: 'Home', keywords: 'widgets home' }
		]
	},
	{
		id: 'assistant',
		label: 'Assistant',
		summary: 'How Mimi answers, sounds and listens.',
		icon: Sparkles,
		ownerOnly: false,
		keywords: 'personality concise detailed formal casual wit instructions about me citations mode voice speech speed read aloud whisper transcription',
		subsections: [
			{ id: 'style', label: 'Answers', keywords: 'length tone wit activity mode' },
			{ id: 'about', label: 'About you', keywords: 'about me custom instructions' },
			{ id: 'voice', label: 'Voice', keywords: 'voice speech speed read aloud transcription whisper' }
		]
	},
	{
		id: 'intelligence',
		label: 'Intelligence',
		summary: 'Models, the offline library, and the tools Mimi can use.',
		icon: Cpu,
		ownerOnly: true,
		keywords: 'model gemma qwen profile context creativity temperature think library collections wikipedia zim sources passages tools plugins extensions community',
		subsections: [
			{ id: 'models', label: 'Models', keywords: 'model profile context creativity think preload' },
			{ id: 'library', label: 'Library', keywords: 'collections wikipedia zim sources passages articles' },
			{ id: 'tools', label: 'Tools', keywords: 'tools plugins community extensions' }
		]
	},
	{
		id: 'location',
		label: 'Maps & location',
		summary: 'Where Mimi thinks it is, GPS, trip history.',
		icon: MapPin,
		ownerOnly: true,
		keywords: 'gps location map history live trips',
		subsections: []
	},
	{
		id: 'sharing',
		label: 'Sharing & access',
		summary: 'Let phones and laptops on the network use Mimi.',
		icon: Share2,
		ownerOnly: true,
		keywords: 'wifi hotspot share phones qr guests network certificate browser url remote access lan other devices',
		subsections: [
			{ id: 'access', label: 'Access', keywords: 'share network address qr firewall' },
			{ id: 'wifi', label: "Mimi's Wi-Fi", keywords: 'wifi hotspot router password' },
			{ id: 'guests', label: 'Guests', keywords: 'guests limits' }
		]
	},
	{
		id: 'accounts',
		label: 'Accounts & privacy',
		summary: 'Your PIN, history, memory and the people who use Mimi.',
		icon: Users,
		ownerOnly: false,
		keywords: 'users people pin password guests privacy history delete chats memory',
		subsections: [
			{ id: 'you', label: 'You', keywords: 'pin password' },
			{ id: 'privacy', label: 'Privacy', keywords: 'history delete memory' },
			{ id: 'people', label: 'People', keywords: 'users add remove' }
		]
	},
	{
		id: 'controls',
		label: 'Controls',
		summary: 'Gamepad buttons and keyboard shortcuts.',
		icon: Gamepad2,
		ownerOnly: true,
		keywords: 'gamepad controller buttons mapping keyboard shortcuts',
		subsections: []
	},
	{
		id: 'system',
		label: 'System',
		summary: 'Storage, services, logs, backup, about.',
		icon: HardDrive,
		ownerOnly: true,
		keywords: 'disk storage logs restart hardware about version export import backup licenses',
		subsections: []
	}
];

/** Old section slugs (bookmarks, other components, muscle memory) → where they live now. */
export const SETTINGS_REDIRECTS: Record<string, { section: string; sub?: string }> = {
	general: { section: 'device' },
	power: { section: 'device', sub: 'power' },
	voice: { section: 'assistant', sub: 'voice' },
	models: { section: 'intelligence', sub: 'models' },
	library: { section: 'intelligence', sub: 'library' },
	tools: { section: 'intelligence', sub: 'tools' }
};

/** Canonical URL for a section (and optional sub-section anchor). Accepts old slugs. */
export function settingsHref(id: string, sub?: string): string {
	const r = SETTINGS_REDIRECTS[id];
	const section = r?.section ?? id;
	const anchor = sub ?? r?.sub;
	return `/settings/${section}${anchor ? '#' + anchor : ''}`;
}

/** Sections a user may see, optionally filtered by a search query (matches labels and keywords, sub-sections included). */
export function visibleSections(isOwner: boolean, query = ''): SettingsSection[] {
	const q = query.trim().toLowerCase();
	return SETTINGS_SECTIONS.filter((s) => (!s.ownerOnly || isOwner) && (!q || [s.label, s.keywords, ...s.subsections.flatMap((x) => [x.label, x.keywords])].join(' ').toLowerCase().includes(q)));
}
