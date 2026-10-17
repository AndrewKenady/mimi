import { fmtNumber, plural, type Messages } from '../index.svelte';

// Core's item_noun (English, singular or plural) → this language's forms.
const NOUNS: Record<string, [one: string, other: string]> = {
	article: ['artículo', 'artículos'],
	document: ['documento', 'documentos'],
	talk: ['charla', 'charlas'],
	video: ['video', 'videos'],
	book: ['libro', 'libros'],
	page: ['página', 'páginas'],
	item: ['elemento', 'elementos']
};
const noun = (s: string) => NOUNS[s.replace(/s$/, '')];

// Core's collection ids (core/mimi/kiwix.py COLLECTIONS).
const COLLECTIONS: Record<string, string> = {
	medicine: 'Medicina',
	encyclopedia: 'Enciclopedia',
	travel: 'Viajes',
	repair: 'Guías de reparación',
	survival: 'Supervivencia',
	dictionary: 'Diccionario',
	qa: 'Preguntas y respuestas',
	books: 'Libros',
	talks: 'Charlas',
	courses: 'Cursos',
	other: 'Otros'
};

export default {
	title: 'Biblioteca',
	myFiles: 'Mis archivos',
	back: 'Atrás',
	clear: 'Borrar',
	loading: 'Cargando…',
	askMimi: 'Preguntar a Mimi',
	notFoundTitle: 'No está en la biblioteca',
	backToLibrary: 'Volver a la biblioteca',

	itemCount: (p: { n: number; noun: string }) => {
		const f = noun(p.noun);
		return f ? plural(p.n, { one: `# ${f[0]}`, other: `# ${f[1]}` }) : `${fmtNumber(p.n)} ${p.noun}`;
	},
	collections: (p: { n: number }) => plural(p.n, { one: '# colección', other: '# colecciones' }),
	pages: (p: { n: number }) => plural(p.n, { one: '# página', other: '# páginas' }),
	pageN: 'página {n}',
	collection: (p: { id: string; label: string }) => COLLECTIONS[p.id] ?? p.label,

	subtitleEmpty: 'Tus obras de consulta, sin conexión',
	offline: 'sin conexión',
	searchPlaceholder: 'Buscar en todos los artículos, guías y respuestas…',
	all: 'Todas',
	askAbout: 'Preguntar a Mimi: {q}',
	noMatches: 'Sin resultados. Prueba con otras palabras.',
	emptyTitle: 'La biblioteca se está preparando',
	emptyBody: 'Las colecciones aparecen aquí en cuanto terminan de descargarse.',
	cantOpenBook: 'Mimi no puede abrir este libro.',
	statusReady: 'Listo',
	statusIndexing: 'Indexando…',
	statusChecking: 'Comprobando…',
	statusUnreadable: 'No se puede abrir',
	statusBrowseOnly: 'Solo lectura',
	statusSearchOnly: 'Solo búsqueda',

	incompleteTitle: (p: { n: number }) => plural(p.n, { one: '# libro no terminó de descargarse', other: '# libros no terminaron de descargarse' }),
	incompleteRest: (p: { n: number }) => plural(p.n, { one: ', así que todavía no aparece en la biblioteca.', other: ', así que todavía no aparecen en la biblioteca.' }),
	incompleteSize: '{done} de {total}',
	incompleteNotBook: 'no es un archivo de libro legible',
	incompleteHint: 'Vuelve a ejecutar tu comando de instalación, o {cmd} para su paquete: las descargas continúan donde se quedaron.',

	collectionMissing: 'Esta colección no está en la biblioteca.',
	filterPlaceholder: (p: { noun: string }) => `Filtrar ${noun(p.noun)?.[1] ?? p.noun} por título o autor…`,
	filterNoMatch: 'Nada coincide con ese filtro.',
	collectionEmpty: 'Mimi no encontró nada que mostrar en esta colección.',
	showMore: (p: { n: number }) => plural(p.n, { one: 'Mostrar más (queda #)', other: 'Mostrar más (quedan #)' }),
	typeVideo: 'Video',
	typeAudio: 'Audio',
	typeImage: 'Imagen',
	typePage: 'Página',
	typeText: 'Texto',
	typeFile: 'Archivo',
	searchable: 'Se puede buscar',
	searchIndexing: 'Preparando para la búsqueda…',
	notSearchable: 'No se puede buscar',

	articleNotFound: 'Artículo no encontrado',
	externalLink: 'Ese enlace apunta a internet. La biblioteca de Mimi funciona sin conexión.',
	openInNewTab: 'Abrir en una pestaña nueva',
	download: 'Descargar',
	smallerText: 'Texto más pequeño',
	largerText: 'Texto más grande',
	contents: 'Contenido',
	cantShowTitle: 'Mimi no puede mostrar este tipo de archivo',
	cantShowBody: '{type} se abre en otra aplicación. Descárgalo para guardar una copia.',
	thisFile: 'Este archivo',
	askDocument: 'Según “{title}” de {book}, ¿cuáles son los puntos clave?',
	askDocumentPage: 'Según “{title}” de {book}, ¿cuáles son los puntos clave de la página {page}?',
	askArticle: 'Según el artículo de la biblioteca “{title}” ({book}), ¿cuáles son los puntos clave?',

	filesIntro: 'Documentos y notas de Scribe en los que Mimi puede buscar cuando haces preguntas. Nunca salen de este dispositivo.',
	dropFiles: 'Suelta archivos aquí o toca para agregarlos',
	dropHint: 'PDF, Word, texto, Markdown, HTML, CSV · hasta 60 MB',
	searchFiles: 'Buscar dentro de tus archivos',
	noFileMatches: 'Sin resultados.',
	noFiles: 'Todavía no hay archivos.',
	addingFile: 'Agregando “{name}” a tu biblioteca…',
	scribeNote: 'Nota de Scribe',
	passages: (p: { n: number }) => plural(p.n, { one: '# fragmento', other: '# fragmentos' }),
	fileReady: 'Listo',
	fileIndexing: 'Indexando',
	fileError: 'Error',
	deleteFile: 'Eliminar {title}'
} satisfies Messages['library'];
