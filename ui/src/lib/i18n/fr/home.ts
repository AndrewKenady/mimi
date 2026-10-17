import { plural, type Messages } from '../index.svelte';

const NOTE_STATUS: Record<string, string> = { queued: 'en attente', transcribing: 'transcription', summarizing: 'résumé en cours', error: 'erreur' };

export default {
	greetingNight: (p: { name: string }) => (p.name ? `Encore debout, ${p.name} ?` : 'Encore debout ?'),
	greetingMorning: (p: { name: string }) => (p.name ? `Bonjour, ${p.name}.` : 'Bonjour.'),
	greetingAfternoon: (p: { name: string }) => (p.name ? `Bonjour, ${p.name}.` : 'Bonjour.'),
	greetingEvening: (p: { name: string }) => (p.name ? `Bonsoir, ${p.name}.` : 'Bonsoir.'),
	ledeLibrary: (p: { n: number }) =>
		plural(p.n, {
			one: '# million de pages de savoir, plus des cartes et des guides. Le tout sur cet appareil.',
			other: '# millions de pages de savoir, plus des cartes et des guides. Le tout sur cet appareil.'
		}),
	ledeEmpty: 'Que voulez-vous savoir ?',
	composerPlaceholder: 'Posez une question à Mimi…',

	talk: 'Parler',
	readPhoto: 'Lire une photo',
	recordNote: 'Enregistrer une note',
	whatsNearby: 'Autour de moi',

	discover: 'Découvrir',
	anotherArticle: 'Un autre article',
	libraryNotReady: 'Votre bibliothèque est encore en préparation.',
	nearby: 'À proximité',
	map: 'Carte',
	nothingClose: 'Rien de notable à proximité.',
	setLocationHint: 'Définissez votre position pour voir les lieux, les parcs et l’histoire autour de vous.',
	setLocation: 'Définir la position',
	continue: 'Reprendre',
	allChats: 'Toutes les discussions',
	chatsEmpty: 'Vos discussions apparaîtront ici.',
	untitled: 'Sans titre',
	recentNotes: 'Notes récentes',
	notesEmpty: 'Enregistrez une réunion ou une idée, et Mimi en rédige le résumé.',
	startRecording: 'Commencer l’enregistrement',
	noteStatus: (p: { status: string }) => `${NOTE_STATUS[p.status] ?? p.status}…`,
	tellMeAbout: 'Parle-moi de {name}',
	libraryLine: (p: { collections: number; articles: number }) =>
		`${plural(p.collections, { one: '# collection hors ligne', other: '# collections hors ligne' })} · ${plural(p.articles, { one: '# article', other: '# articles' })}`
} satisfies Messages['home'];
