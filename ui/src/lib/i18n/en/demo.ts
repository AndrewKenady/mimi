// Text for the demo area: the browser demo's banner, guided tour and the stand-in Core's own
// replies. The recorded answers themselves stay in English (demo/recorded.json). Keys are
// camelCase; see docs/I18N.md.
import { plural } from '../index.svelte';

export default {
	// The banner
	liveDemo: 'Live demo',
	answerPlaying: ', an answer is playing',
	about: 'About this demo',
	what: '— the real Mimi interface, running in your browser on recorded answers.',
	real: 'The real thing runs offline on your own device.',
	aboutMimi: 'About Mimi',
	caseStudy: 'Case study',
	newTab: '(opens in a new tab)',
	fold: 'Fold the demo banner',
	foldTitle: 'Fold',
	replayFast: 'Replaying 8× faster than the handheld.',
	replayReal: 'Replaying at the handheld’s real speed: sources first, then the answer.',
	replayRealShort: 'Handheld speed: sources first, then the answer.',
	tryMimi: 'Try Mimi',
	stepOf: 'Step {n} of {total}:',
	tourDone: 'Tour done. Explore freely.',
	/** Before the recorded questions, which are in English. */
	orTry: 'or try',
	skipWait: 'Skip the wait',

	// The guided tour (the first step sends the recorded English question)
	tourAsk: 'Ask how to treat hypothermia',
	tourAskShort: 'Ask about hypothermia',
	tourLibrary: 'Open the Medical Library',
	tourLibraryShort: 'Medical Library',
	tourDesign: 'See the design system',
	tourDesignShort: 'Design system',

	/** The answer to a question with no recording; the questions are the recorded (English) ones. */
	honest: (p: { questions: string[] }) =>
		"This demo plays recorded answers, so I can't look that up here. Try one of these:\n\n" +
		p.questions.map((q) => `- ${q}`).join('\n') +
		"\n\nOn a real Mimi, I'd search the offline library on your device and answer with sources.",

	// What needs the device says so ({what} is one of the features below)
	notHere: "{what} isn't available in the browser demo. On a real Mimi it runs on the device itself, offline.",
	importingSettings: 'Importing settings',
	signingInDevices: 'Signing in other devices',
	attachingFiles: 'Attaching files',
	addingFiles: 'Adding your own files',
	speechRecognition: 'Speech recognition',
	readingAloud: 'Reading answers aloud',
	readingPhotos: 'Reading photos',
	recordingNotes: 'Recording notes',
	noModels: "Models don't run in the browser demo: the answers here were recorded from a real Mimi.",
	deviceOnly: "That changes the device itself, so it isn't part of the browser demo.",
	notPart: "That isn't part of the browser demo.",
	notPartShort: 'Not part of the browser demo',
	noCollection: 'This collection is not in the library.',
	noArticle: "That article isn't part of the browser demo's recorded library.",
	noBookPages: "That book's pages aren't part of the browser demo.",
	noDirections: "Offline directions aren't part of this demo.",
	setLocation: 'Set your location first (tap the map), or connect a GPS.',
	oneRoute: 'This demo has one recorded route: from Old Faithful to {to}. Search for {to} to see it.',

	// A PDF opened in the reader
	pages: (p: { n: number }) => plural(p.n, { one: '# page', other: '# pages' }),
	docTitle: 'Not in the browser demo',
	docOnReal: 'On a real Mimi this PDF opens right here, offline, in the browser’s own viewer, and a citation to one of its pages jumps straight to that page.',
	docNoFiles: 'The demo doesn’t carry the {book}’s files, so there is nothing to open. The list of documents, their sizes and page counts are recorded from Mimi.',

	// Camera, microphone, sign-out and links to Core
	camera: "The camera isn't used in the browser demo. On a real Mimi, Lens reads photos on the device itself.",
	mic: "The microphone isn't used in the browser demo. On a real Mimi, voice and Scribe run on the device itself.",
	oneAccount: 'The browser demo has one account, so you stay signed in as {name}.',
	downloads: "Downloads and exports come from Mimi itself, so they aren't part of the browser demo.",
	deviceFile: "That file lives on the device, so it isn't part of the browser demo."
};
