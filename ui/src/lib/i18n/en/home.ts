// Text for the home area. Keys are camelCase; see docs/I18N.md.
import { fmtNumber } from '../index.svelte';

export default {
	// The greeting, by time of day; `name` is empty for a guest.
	greetingNight: (p: { name: string }) => (p.name ? `Still up, ${p.name}.` : 'Still up.'),
	greetingMorning: (p: { name: string }) => (p.name ? `Good morning, ${p.name}.` : 'Good morning.'),
	greetingAfternoon: (p: { name: string }) => (p.name ? `Good afternoon, ${p.name}.` : 'Good afternoon.'),
	greetingEvening: (p: { name: string }) => (p.name ? `Good evening, ${p.name}.` : 'Good evening.'),
	/** `n` is millions of library pages, rounded. */
	ledeLibrary: (p: { n: number }) => `${p.n} million pages of knowledge, plus maps and guides. All on this device.`,
	ledeEmpty: 'What would you like to know?',
	composerPlaceholder: 'Ask Mimi anything…',

	// Quick actions
	talk: 'Talk',
	readPhoto: 'Read a photo',
	recordNote: 'Record a note',
	whatsNearby: "What's nearby",

	// Widgets
	discover: 'Discover',
	anotherArticle: 'Another article',
	libraryNotReady: 'Your library is still getting ready.',
	nearby: 'Nearby',
	map: 'Map',
	nothingClose: 'Nothing notable close by.',
	setLocationHint: 'Set your location to see places, parks and history around you.',
	setLocation: 'Set location',
	continue: 'Continue',
	allChats: 'All chats',
	chatsEmpty: 'Your conversations will show up here.',
	untitled: 'Untitled',
	recentNotes: 'Recent notes',
	notesEmpty: 'Record a meeting or a thought, and Mimi writes the summary.',
	startRecording: 'Start recording',
	/** A Scribe note still being worked on: queued, transcribing, summarizing or error. */
	noteStatus: (p: { status: string }) => `${p.status}…`,
	/** Sent to Mimi when a nearby place has no article; it shows in the chat as your own words. */
	tellMeAbout: 'Tell me about {name}',
	libraryLine: (p: { collections: number; articles: number }) => `${p.collections} offline collections · ${fmtNumber(p.articles)} articles`
};
