// Text for the memory area. Keys are camelCase; see docs/I18N.md.
export default {
	pageTitle: 'Memory · Mimi',
	heading: 'Memory',
	intro: "What Mimi knows about you, so it can help without asking twice. It stays on this device, and you're in control of every word.",

	// Kinds of memory
	catPersonal: 'About you',
	catPreference: 'Preferences',
	catProject: 'Projects',
	catOther: 'Other',

	// Settings
	settingsLabel: 'Memory settings',
	modeLabel: 'Memory mode',
	modeAsk: 'Ask first',
	modeAuto: 'Automatic',
	modeOff: 'Off',
	explainAsk: 'Mimi suggests things to remember, and you approve each one.',
	explainAuto: 'Mimi saves lasting facts on its own. You can review them here.',
	explainOff: "Mimi won't save or use memories.",
	resume: 'Resume memory',
	pause: 'Pause memory',
	export: 'Export',
	eraseAll: 'Erase all',
	pausedNote: "Memory is paused. Mimi isn't using or saving memories right now.",

	// Suggestions
	waiting: 'Waiting for your OK',
	keep: 'Keep',
	keepItem: 'Keep: {text}',
	discard: 'Discard',
	discardItem: 'Discard: {text}',
	discarded: 'Suggestion discarded',

	// The list
	search: 'Search memories',
	searchPlaceholder: 'Search memories',
	show: 'Show',
	all: 'All',
	add: 'Add',
	newLabel: 'Something to remember',
	newPlaceholder: "e.g. I'm allergic to penicillin",
	kind: 'Kind',
	save: 'Save',
	editLabel: 'Edit memory',
	cancel: 'Cancel',
	pinned: 'Pinned',
	used: (p: { n: number }) => `used ${p.n}×`,
	fromChat: 'from a chat',
	unpin: 'Unpin',
	alwaysUse: 'Always use',
	pinItem: 'Pin: always use',
	edit: 'Edit',
	editItem: 'Edit: {text}',
	forget: 'Forget',
	forgetItem: 'Forget: {text}',
	forgotten: 'Forgotten',
	// "No memories yet. Tell Mimi something like “…”, or add one yourself." with the example in italics
	emptyBefore: 'No memories yet. Tell Mimi something like ',
	emptyExample: '“Remember that I drive a 2014 Tacoma”',
	emptyAfter: ', or add one yourself.',

	// Erase everything
	wipeTitle: 'Erase every memory?',
	wipeBody: (p: { n: number }) =>
		p.n === 1
			? 'Mimi will forget the one thing it knows about you. This can’t be undone. You can export it first.'
			: `Mimi will forget all ${p.n} things it knows about you. This can’t be undone. You can export them first.`,
	wipeConfirm: 'Erase all',
	wiped: 'All memories erased'
};
