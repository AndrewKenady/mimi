import { plural, type Messages } from '../index.svelte';

const NOTE_STATUS: Record<string, string> = { queued: 'en cola', transcribing: 'transcribiendo', summarizing: 'resumiendo', error: 'error' };

export default {
	greetingNight: (p: { name: string }) => (p.name ? `¿Trasnochando, ${p.name}?` : '¿Trasnochando?'),
	greetingMorning: (p: { name: string }) => (p.name ? `Buenos días, ${p.name}.` : 'Buenos días.'),
	greetingAfternoon: (p: { name: string }) => (p.name ? `Buenas tardes, ${p.name}.` : 'Buenas tardes.'),
	greetingEvening: (p: { name: string }) => (p.name ? `Buenas noches, ${p.name}.` : 'Buenas noches.'),
	ledeLibrary: (p: { n: number }) =>
		plural(p.n, {
			one: '# millón de páginas de conocimiento, además de mapas y guías. Todo en este dispositivo.',
			other: '# millones de páginas de conocimiento, además de mapas y guías. Todo en este dispositivo.'
		}),
	ledeEmpty: '¿Qué te gustaría saber?',
	composerPlaceholder: 'Pregúntale a Mimi lo que quieras…',

	talk: 'Hablar',
	readPhoto: 'Leer una foto',
	recordNote: 'Grabar una nota',
	whatsNearby: 'Qué hay cerca',

	discover: 'Descubre',
	anotherArticle: 'Otro artículo',
	libraryNotReady: 'Tu biblioteca aún se está preparando.',
	nearby: 'Cerca',
	map: 'Mapa',
	nothingClose: 'No hay nada destacado cerca.',
	setLocationHint: 'Indica tu ubicación para ver lugares, parques e historia a tu alrededor.',
	setLocation: 'Indicar ubicación',
	continue: 'Continuar',
	allChats: 'Todos los chats',
	chatsEmpty: 'Tus conversaciones aparecerán aquí.',
	untitled: 'Sin título',
	recentNotes: 'Notas recientes',
	notesEmpty: 'Graba una reunión o una idea, y Mimi escribe el resumen.',
	startRecording: 'Empezar a grabar',
	noteStatus: (p: { status: string }) => `${NOTE_STATUS[p.status] ?? p.status}…`,
	tellMeAbout: 'Háblame de {name}',
	libraryLine: (p: { collections: number; articles: number }) =>
		`${plural(p.collections, { one: '# colección sin conexión', other: '# colecciones sin conexión' })} · ${plural(p.articles, { one: '# artículo', other: '# artículos' })}`
} satisfies Messages['home'];
