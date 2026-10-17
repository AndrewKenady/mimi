// Text for the app frame shared by every screen: the nav rail and phone tab bar, the status
// strip, the command palette, the quick menu, toasts and the confirm dialog. Keys are
// camelCase; see docs/I18N.md.
import { plural } from '../index.svelte';

export default {
	// Navigation: the rail on wide screens, the tab bar on phones
	navMain: 'Main',
	home: 'Home',
	chat: 'Chat',
	library: 'Library',
	map: 'Map',
	scribe: 'Scribe',
	lens: 'Lens',
	memory: 'Memory',
	settings: 'Settings',
	talk: 'Talk',
	more: 'More',
	talkTitle: 'Talk to Mimi: tap and speak (X on a controller)',
	quickMenu: 'Quick menu',
	/** The brand mark's accessible name; {status} is one of the presence lines below. */
	brandLabel: 'Mimi home. {status}',
	presenceOffline: 'Mimi can’t be reached',
	presenceWaking: 'Waking up {name}…',
	presenceWakingModel: 'Waking up the model…',
	presenceError: 'The model needs attention',

	// Status strip
	deviceStatus: 'Device status',
	offlineTitle: 'Mimi runs entirely on this device',
	offlineAllLocal: 'Offline · all local',
	modelTitle: 'Language model',
	modelNone: 'No model',
	modelWaking: 'Waking {name}…',
	modelWakingModel: 'Waking model…',
	modelUnavailable: 'Model unavailable',
	modelIdle: 'Model idle',
	saverTitle: 'Battery saver: using the quick model',
	saver: 'Saver',
	locationLive: 'Live location from this device',
	location: 'Location',
	sharedTitle: 'Other devices can open Mimi at this address',
	shared: 'Shared · {address}',
	/** Devices connected to this Mimi over the network. */
	connected: (p: { n: number }) => plural(p.n, { one: '# connected', other: '# connected' }),
	battery: 'Battery',

	// Command palette
	palette: 'Command palette',
	paletteSearch: 'Search chats, go anywhere, or ask…',
	paletteSearchLabel: 'Search chats, places and commands',
	/** The Escape key, as printed on the keyboard. */
	paletteEsc: 'Esc',
	paletteResults: 'Results',
	paletteNone: 'Nothing matches “{q}”.',
	groupGo: 'Go',
	groupSettings: 'Settings',
	groupActions: 'Actions',
	groupChats: 'Chats',
	groupAsk: 'Ask',
	newChat: 'New chat',
	talkToMimi: 'Talk to Mimi',
	voice: 'Voice',
	scribeCommand: 'Scribe — record a note',
	lensCommand: 'Lens — read a photo',
	settingsSection: 'Settings: {section}',
	settingsSubsection: 'Settings: {section} › {sub}',
	toggleTheme: 'Toggle light / dark',
	toggleFullscreen: 'Toggle full screen',
	shareCommand: 'Share Mimi with nearby phones',
	/** {name} is the language's name in that language: English, Español, Français. */
	languageCommand: 'Language: {name}',
	languageCurrent: 'Current',
	untitledChat: 'Untitled chat',
	askMimi: 'Ask Mimi: “{q}”',

	// Quick menu
	search: 'Search',
	share: 'Share',
	darkMode: 'Dark mode',
	lightMode: 'Light mode',
	fullScreen: 'Full screen',
	exitToDesktop: 'Exit to desktop',
	signOut: 'Sign out',
	owner: 'Owner',
	guest: 'Guest',
	member: 'Member',
	/** After the person's role: "Owner · connected over the network". */
	overNetwork: 'connected over the network',
	account: 'Account',

	// Toasts, the confirm dialog and connection state
	dismiss: 'Dismiss',
	undo: 'Undo',
	reload: 'Reload',
	updated: 'Mimi was updated.',
	saveFailed: 'Could not save that setting',
	deleteFailed: 'Could not delete that',
	noLocationSensor: 'This device has no location sensor available.',
	locationDenied: 'Location permission was denied for this browser.',
	noLocationFix: 'No location fix yet. Mimi will keep trying.',
	sharingLocation: 'Sharing this device’s live location with Mimi',
	cancel: 'Cancel',
	confirm: 'Confirm',
	/** Under the confirm dialog when a game controller is in use. */
	padCancel: 'B to cancel',
	reconnecting: 'Reconnecting to Mimi Core…',
	/** The boot splash's accessible name while the app loads. */
	starting: 'Mimi is starting',

	// Shared helpers (api.ts)
	requestFailed: 'Request failed ({status})',
	justNow: 'just now',
	minutesAgo: '{n}m ago',
	hoursAgo: '{n}h ago',
	daysAgo: '{n}d ago',
	/** Byte, kilobyte, megabyte, gigabyte, terabyte, separated by spaces. */
	byteUnits: 'B KB MB GB TB'
};
