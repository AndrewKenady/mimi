// The sections of Settings, in order. One list for the Settings page and the command palette.
import {
	SlidersHorizontal, Palette, Sparkles, Cpu, AudioLines, Library, MapPin, Share2, Users, Gamepad2, BatteryCharging, HardDrive, Puzzle
} from '@lucide/svelte';

export type SettingsSection = {
	id: string;
	label: string;
	icon: any;
	/** Only the device owner sees it. */
	owner: boolean;
	/** Extra words that find it in search. */
	keys: string;
};

export const SETTINGS_SECTIONS: SettingsSection[] = [
	{ id: 'general', label: 'General', icon: SlidersHorizontal, owner: true, keys: 'startup full screen kiosk units time pin lock' },
	{ id: 'appearance', label: 'Appearance', icon: Palette, owner: false, keys: 'theme dark light oled accent color font size motion contrast well widgets' },
	{ id: 'assistant', label: 'Assistant', icon: Sparkles, owner: false, keys: 'personality concise detailed formal casual wit instructions about me citations mode' },
	{ id: 'models', label: 'Models', icon: Cpu, owner: true, keys: 'model gemma qwen profile context creativity temperature think' },
	{ id: 'voice', label: 'Voice', icon: AudioLines, owner: false, keys: 'voice speech speed read aloud whisper transcription' },
	{ id: 'library', label: 'Library', icon: Library, owner: true, keys: 'collections wikipedia zim sources passages' },
	{ id: 'location', label: 'Maps & Location', icon: MapPin, owner: true, keys: 'gps location map history' },
	{ id: 'tools', label: 'Tools', icon: Puzzle, owner: true, keys: 'tools plugins extensions community sunrise sunset units convert calculator directions search' },
	{ id: 'sharing', label: 'Sharing & access', icon: Share2, owner: true, keys: 'wifi hotspot share phones qr guests network certificate browser url remote access lan other devices' },
	{ id: 'accounts', label: 'Accounts & Privacy', icon: Users, owner: false, keys: 'users pin password guests privacy history delete memory' },
	{ id: 'controls', label: 'Controls', icon: Gamepad2, owner: true, keys: 'gamepad controller buttons mapping keyboard shortcuts' },
	{ id: 'power', label: 'Power', icon: BatteryCharging, owner: true, keys: 'battery saver power' },
	{ id: 'system', label: 'Storage & System', icon: HardDrive, owner: true, keys: 'disk storage logs restart hardware about version export import licenses' }
];
