// Text for the library area. Keys are camelCase; see docs/I18N.md.
import { fmtNumber, plural } from '../index.svelte';

// What a book holds, as Core names it in `item_noun` (singular or plural English: "article",
// "documents", "talks"…). Known nouns get this language's plural forms; any other noun shows
// Core's own word.
const NOUNS: Record<string, [one: string, other: string]> = {
	article: ['article', 'articles'],
	document: ['document', 'documents'],
	talk: ['talk', 'talks'],
	video: ['video', 'videos'],
	book: ['book', 'books'],
	page: ['page', 'pages'],
	item: ['item', 'items']
};
const noun = (s: string) => NOUNS[s.replace(/s$/, '')];

export default {
	title: 'Library',
	myFiles: 'My files',
	back: 'Back',
	clear: 'Clear',
	loading: 'Loading…',
	askMimi: 'Ask Mimi',
	notFoundTitle: 'Not in the library',
	backToLibrary: 'Back to the library',

	// Counts. `noun` is Core's item_noun; unknown nouns fall back to Core's word.
	itemCount: (p: { n: number; noun: string }) => {
		const f = noun(p.noun);
		return f ? plural(p.n, { one: `# ${f[0]}`, other: `# ${f[1]}` }) : `${fmtNumber(p.n)} ${p.noun}`;
	},
	collections: (p: { n: number }) => plural(p.n, { one: '# collection', other: '# collections' }),
	pages: (p: { n: number }) => plural(p.n, { one: '# page', other: '# pages' }),
	pageN: 'page {n}',
	/** A collection's name, by Core's collection id; `label` is Core's English name, the fallback. */
	collection: (p: { id: string; label: string }) => p.label,

	// The shelf
	subtitleEmpty: 'Your offline reference shelf',
	offline: 'offline',
	searchPlaceholder: 'Search every article, guide and answer…',
	all: 'All',
	/** `{q}` is the search, shown in bold. */
	askAbout: 'Ask Mimi: {q}',
	noMatches: 'No matches. Try different words.',
	emptyTitle: 'The library is getting ready',
	emptyBody: 'Collections appear here as soon as they finish downloading.',
	cantOpenBook: "Mimi can't open this book.",
	statusReady: 'Ready',
	statusIndexing: 'Indexing…',
	statusChecking: 'Checking…',
	statusUnreadable: "Can't open",
	statusBrowseOnly: 'Browse only',
	statusSearchOnly: 'Search only',

	// Downloads that didn't finish (owner only). The bold part, then the rest of the sentence.
	incompleteTitle: (p: { n: number }) => plural(p.n, { one: "# book didn't finish downloading", other: "# books didn't finish downloading" }),
	incompleteRest: (p: { n: number }) => plural(p.n, { one: ", so it isn't on the shelf yet.", other: ", so they aren't on the shelf yet." }),
	incompleteSize: '{done} of {total}',
	incompleteNotBook: 'not a readable book file',
	/** `{cmd}` is the command, shown in monospace. */
	incompleteHint: 'Run your install command again, or {cmd} for its pack: downloads pick up where they stopped.',

	// A collection's own page (documents, talks, books)
	collectionMissing: 'This collection is not in the library.',
	filterPlaceholder: (p: { noun: string }) => `Filter ${noun(p.noun)?.[1] ?? p.noun} by title or author…`,
	filterNoMatch: 'Nothing matches that filter.',
	collectionEmpty: "Mimi couldn't find anything to list in this collection.",
	showMore: (p: { n: number }) => `Show more (${fmtNumber(p.n)} left)`,
	typeVideo: 'Video',
	typeAudio: 'Audio',
	typeImage: 'Image',
	typePage: 'Page',
	typeText: 'Text',
	typeFile: 'File',
	searchable: 'Searchable',
	searchIndexing: 'Being read for search…',
	notSearchable: 'Not searchable',

	// The reader
	articleNotFound: 'Article not found',
	externalLink: "That link points to the internet. Mimi's library is offline.",
	openInNewTab: 'Open in a new tab',
	download: 'Download',
	smallerText: 'Smaller text',
	largerText: 'Larger text',
	contents: 'Contents',
	cantShowTitle: "Mimi can't show this kind of file",
	/** `{type}` is the file's MIME type, or thisFile. */
	cantShowBody: '{type} opens in another app. Download it to keep a copy.',
	thisFile: 'This file',
	// What "Ask Mimi" sends to the chat, in the reader's words.
	askDocument: 'Using “{title}” from the {book}, give me the key points.',
	askDocumentPage: 'Using “{title}” from the {book}, give me the key points of page {page}.',
	askArticle: 'Using the library article “{title}” ({book}), give me the key points.',

	// My files
	filesIntro: 'Documents and Scribe notes Mimi can search when you ask questions. They never leave this device.',
	dropFiles: 'Drop files here or tap to add',
	dropHint: 'PDF, Word, text, Markdown, HTML, CSV · up to 60 MB',
	searchFiles: 'Search inside your files',
	noFileMatches: 'No matches.',
	noFiles: 'No files yet.',
	addingFile: 'Adding “{name}” to your library…',
	scribeNote: 'Scribe note',
	passages: (p: { n: number }) => plural(p.n, { one: '# passage', other: '# passages' }),
	fileReady: 'Ready',
	fileIndexing: 'Indexing',
	fileError: 'Error',
	deleteFile: 'Delete {title}'
};
