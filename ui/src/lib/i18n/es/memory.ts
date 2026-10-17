import { plural, type Messages } from '../index.svelte';

export default {
	pageTitle: 'Memoria · Mimi',
	heading: 'Memoria',
	intro: 'Lo que Mimi sabe de ti, para ayudarte sin preguntar dos veces. Se queda en este dispositivo y tú controlas cada palabra.',

	catPersonal: 'Sobre ti',
	catPreference: 'Preferencias',
	catProject: 'Proyectos',
	catOther: 'Otros',

	settingsLabel: 'Configuración de la memoria',
	modeLabel: 'Modo de memoria',
	modeAsk: 'Preguntar antes',
	modeAuto: 'Automático',
	modeOff: 'Desactivado',
	explainAsk: 'Mimi sugiere cosas que recordar y tú apruebas cada una.',
	explainAuto: 'Mimi guarda por su cuenta los datos duraderos. Puedes revisarlos aquí.',
	explainOff: 'Mimi no guardará ni usará memorias.',
	resume: 'Reanudar la memoria',
	pause: 'Pausar la memoria',
	export: 'Exportar',
	eraseAll: 'Borrar todo',
	pausedNote: 'La memoria está en pausa. Mimi no está usando ni guardando memorias por ahora.',

	waiting: 'Esperando tu aprobación',
	keep: 'Conservar',
	keepItem: 'Conservar: {text}',
	discard: 'Descartar',
	discardItem: 'Descartar: {text}',
	discarded: 'Sugerencia descartada',

	search: 'Buscar memorias',
	searchPlaceholder: 'Buscar memorias',
	show: 'Mostrar',
	all: 'Todas',
	add: 'Agregar',
	newLabel: 'Algo que recordar',
	newPlaceholder: 'p. ej., Tengo alergia a la penicilina',
	kind: 'Tipo',
	save: 'Guardar',
	editLabel: 'Editar memoria',
	cancel: 'Cancelar',
	pinned: 'Fijada',
	used: (p: { n: number }) => plural(p.n, { one: 'usada # vez', other: 'usada # veces' }),
	fromChat: 'de un chat',
	unpin: 'Desfijar',
	alwaysUse: 'Usar siempre',
	pinItem: 'Fijar: usar siempre',
	edit: 'Editar',
	editItem: 'Editar: {text}',
	forget: 'Olvidar',
	forgetItem: 'Olvidar: {text}',
	forgotten: 'Olvidada',
	emptyBefore: 'Aún no hay memorias. Dile a Mimi algo como ',
	emptyExample: '“Recuerda que manejo una Tacoma 2014”',
	emptyAfter: ' o agrega una por tu cuenta.',

	wipeTitle: '¿Borrar todas las memorias?',
	wipeBody: (p: { n: number }) =>
		plural(p.n, {
			one: 'Mimi olvidará lo único que sabe de ti. No se puede deshacer. Puedes exportarlo antes.',
			other: 'Mimi olvidará las # cosas que sabe de ti. No se puede deshacer. Puedes exportarlas antes.'
		}),
	wipeConfirm: 'Borrar todo',
	wiped: 'Se borraron todas las memorias'
} satisfies Messages['memory'];
