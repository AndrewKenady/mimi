import type { Messages } from '../index.svelte';

export default {
	intro: 'Apunta, dispara y entiende. Mimi lee el texto al instante y puede explicar, traducir o identificar lo que ve, todo sin conexión.',
	noCamera: 'No hay ninguna cámara disponible. Puedes subir una foto.',
	readFailed: 'No se pudo leer esa imagen',

	cancel: 'Cancelar',
	takePhoto: 'Tomar foto',
	switchCamera: 'Cambiar de cámara',
	yourCapture: 'Tu captura',
	openCamera: 'Abrir la cámara',
	choosePhoto: 'Elegir una foto',
	examples: 'Letreros, menús, etiquetas, documentos, plantas, piezas…',

	textFound: 'Texto encontrado',
	hideBoxes: 'Ocultar recuadros',
	showBoxes: 'Mostrar recuadros',
	copyText: 'Copiar texto',
	reading: 'Leyendo…',
	noText: 'No se detectó texto. Aun así, puedes preguntarle a Mimi sobre la imagen.',
	readIn: 'Leído en el dispositivo en {ms} ms',

	askTitle: 'Pregunta sobre esta foto',
	explain: 'Explicar',
	translate: 'Traducir',
	identify: 'Identificar',
	summarize: 'Resumir',
	askPlaceholder: 'O escribe tu pregunta…',
	askLabel: 'Tu pregunta sobre esta foto',
	ask: 'Preguntar',
	newPhoto: 'Nueva foto'
} satisfies Messages['lens'];
