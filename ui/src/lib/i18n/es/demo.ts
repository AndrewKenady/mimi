import type { Messages } from '../index.svelte';
import { plural } from '../index.svelte';

export default {
	liveDemo: 'Demo en vivo',
	answerPlaying: ', se está reproduciendo una respuesta',
	about: 'Acerca de esta demo',
	what: '— la interfaz real de Mimi, en tu navegador, con respuestas grabadas en inglés.',
	real: 'La versión real funciona sin conexión en tu propio dispositivo.',
	aboutMimi: 'Acerca de Mimi',
	caseStudy: 'Caso de estudio',
	newTab: '(se abre en una pestaña nueva)',
	fold: 'Contraer el banner de la demo',
	foldTitle: 'Contraer',
	replayFast: 'Reproduciendo 8× más rápido que en el dispositivo portátil.',
	replayReal: 'Reproduciendo a la velocidad real del dispositivo portátil: primero las fuentes, luego la respuesta.',
	replayRealShort: 'Velocidad real: primero las fuentes, luego la respuesta.',
	tryMimi: 'Prueba Mimi',
	stepOf: 'Paso {n} de {total}:',
	tourDone: 'Recorrido terminado. Explora a tu gusto.',
	orTry: 'o prueba (en inglés)',
	skipWait: 'Saltar la espera',

	tourAsk: 'Pregunta en inglés cómo tratar la hipotermia',
	tourAskShort: 'Hipotermia (en inglés)',
	tourLibrary: 'Abre la Medical Library',
	tourLibraryShort: 'Medical Library',
	tourDesign: 'Mira el sistema de diseño',
	tourDesignShort: 'Sistema de diseño',

	honest: (p: { questions: string[] }) =>
		'Esta demo reproduce respuestas grabadas, así que aquí no puedo buscar eso. Prueba una de estas preguntas (las respuestas grabadas están en inglés):\n\n' +
		p.questions.map((q) => `- ${q}`).join('\n') +
		'\n\nEn un Mimi real, buscaría en la biblioteca sin conexión de tu dispositivo y te respondería citando las fuentes.',

	notHere: '{what} no está disponible en la demo del navegador. En un Mimi real funciona en el propio dispositivo, sin conexión.',
	importingSettings: 'Importar la configuración',
	signingInDevices: 'Iniciar sesión en otros dispositivos',
	attachingFiles: 'Adjuntar archivos',
	addingFiles: 'Agregar tus propios archivos',
	speechRecognition: 'El reconocimiento de voz',
	readingAloud: 'Leer las respuestas en voz alta',
	readingPhotos: 'Leer fotos',
	recordingNotes: 'Grabar notas',
	noModels: 'Los modelos no se ejecutan en la demo del navegador: las respuestas de aquí se grabaron en un Mimi real.',
	deviceOnly: 'Eso cambia el propio dispositivo, así que no forma parte de la demo del navegador.',
	notPart: 'Eso no forma parte de la demo del navegador.',
	notPartShort: 'No forma parte de la demo del navegador',
	noCollection: 'Esta colección no está en la biblioteca.',
	noArticle: 'Ese artículo no forma parte de la biblioteca grabada de la demo del navegador.',
	noBookPages: 'Las páginas de ese libro no forman parte de la demo del navegador.',
	noDirections: 'Las indicaciones sin conexión no forman parte de esta demo.',
	setLocation: 'Primero indica tu ubicación (toca el mapa) o conecta un GPS.',
	oneRoute: 'Esta demo tiene una sola ruta grabada: de Old Faithful a {to}. Busca {to} para verla.',

	pages: (p: { n: number }) => plural(p.n, { one: '# página', other: '# páginas' }),
	docTitle: 'No está en la demo del navegador',
	docOnReal: 'En un Mimi real, este PDF se abre aquí mismo, sin conexión, en el visor del propio navegador, y una cita a una de sus páginas lleva directamente a esa página.',
	docNoFiles: 'La demo no incluye los archivos de {book}, así que no hay nada que abrir. La lista de documentos, sus tamaños y sus números de páginas se grabaron en Mimi.',

	camera: 'La cámara no se usa en la demo del navegador. En un Mimi real, Lens lee las fotos en el propio dispositivo.',
	mic: 'El micrófono no se usa en la demo del navegador. En un Mimi real, la voz y Scribe funcionan en el propio dispositivo.',
	oneAccount: 'La demo del navegador tiene una sola cuenta, así que sigues con la sesión iniciada como {name}.',
	downloads: 'Las descargas y exportaciones vienen del propio Mimi, así que no forman parte de la demo del navegador.',
	deviceFile: 'Ese archivo está en el dispositivo, así que no forma parte de la demo del navegador.'
} satisfies Messages['demo'];
