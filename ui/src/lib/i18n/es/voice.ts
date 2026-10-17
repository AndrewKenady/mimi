import type { Messages } from '../index.svelte';

export default {
	dialog: 'Conversación de voz con Mimi',
	newConversation: 'Nueva conversación',
	close: 'Cerrar el modo de voz',

	listening: 'Escuchando…',
	transcribing: 'Transcribiendo lo que dijiste…',
	thinking: 'Preparando una respuesta…',
	tapToTalk: 'Toca el micrófono para hablar',
	startingFresh: 'Empezamos de nuevo.',
	micUnavailable: 'El micrófono no está disponible aquí. Puedes escribir en su lugar.',
	heardNothing: 'No escuché nada. Toca el micrófono y habla.',
	tapAndSpeak: 'Toca el micrófono y habla.',
	didntCatch: 'No te entendí. ¿Lo intentamos de nuevo?',
	quoted: '“{text}”',

	doneTalking: 'Terminé de hablar',
	interrupt: 'Interrumpir y hablar',
	startTalking: 'Empezar a hablar',
	typeQuestion: 'Escribe tu pregunta',
	send: 'Enviar',
	typeInstead: 'Escribir en su lugar',

	pauseTap: 'Haz una pausa cuando termines, o toca el botón para enviar',
	pausePress: 'Haz una pausa cuando termines, o presiona el botón para enviar',
	pauseClick: 'Haz una pausa cuando termines, o haz clic en el botón para enviar',
	interruptTap: 'Toca el botón para interrumpir',
	interruptPress: 'Presiona el botón para interrumpir',
	interruptClick: 'Haz clic en el botón para interrumpir',
	talkPad: 'Presiona A en el micrófono para hablar',
	talkClick: 'Haz clic en el micrófono o presiona Espacio',
	padClose: 'B para cerrar',

	fillerLookUp: 'Déjame buscarlo.',
	fillerFiles: 'Reviso tus archivos.',
	fillerNearby: 'Veamos qué hay cerca.',
	fillerWhere: 'Veo dónde estamos.',
	fillerRoute: 'Déjame calcular la ruta.',
	fillerPicture: 'Déjame buscar una imagen.',
	fillerWait: 'Un momento.'
} satisfies Messages['voice'];
