import type { Messages } from '../index.svelte';

export default {
	back: 'Atrás',
	step: 'Paso {n} de {total}',
	continue: 'Continuar',

	hello: 'Hola. Soy Mimi.',
	tagline: 'Inteligencia artificial, sin internet.',
	livesHere: 'Todo lo que sé vive aquí mismo, en este dispositivo.',
	begin: 'Comencemos',

	nameTitle: '¿Cómo quieres que te llame?',
	nameSub: 'Tendrás la cuenta de propietario de este Mimi. Otras personas pueden unirse más tarde como invitados o usuarios.',
	yourName: 'Tu nombre',
	setPin: 'Crear un PIN',
	setPinNote: 'Lo necesitas para iniciar sesión desde tu teléfono o tu computadora portátil, y mantiene privadas tu configuración y tu memoria.',
	pinLabel: 'PIN (de 4 a 8 dígitos)',
	settingUp: 'Configurando…',
	errName: 'Por favor, dime tu nombre.',
	errPin: 'El PIN debe tener de 4 a 8 dígitos.',

	lookTitle: 'Hazlo tuyo',
	lookSub: 'Elige un estilo. Puedes cambiarlo todo más tarde en Configuración.',
	theme: 'Tema',
	accent: 'Color de acento',

	voiceTitle: 'Elige mi voz',
	voiceSub: 'Así sonaré cuando hablemos. Elige una para escuchar una muestra.',
	voice: 'Voz',
	americanEnglish: 'Inglés estadounidense',
	sample: 'Hola, {name}, soy Mimi. Todo lo que sé vive aquí mismo, en este dispositivo.',
	sampleNoName: 'Hola, soy Mimi. Todo lo que sé vive aquí mismo, en este dispositivo.',

	memoryTitle: '¿Cómo debo recordar las cosas?',
	memorySub: 'Las memorias se quedan en este dispositivo. Puedes ver, editar o borrar cada una de ellas.',
	memory: 'Memoria',
	memoryAsk: 'Pregúntame primero',
	memoryAskNote: 'Te sugiero memorias y tú las apruebas. Recomendado.',
	memoryAuto: 'Recordar automáticamente',
	memoryAutoNote: 'Guardo datos duraderos mientras hablamos. Puedes revisarlos cuando quieras.',
	memoryOff: 'No recordar',
	memoryOffNote: 'Cada conversación empieza de cero.',

	doneTitle: 'Todo listo, {name}.',
	tipAsk: 'Pregunta lo que quieras. Lo buscaré en la biblioteca sin conexión y te mostraré mis fuentes.',
	tipTalkTap: 'Toca Hablar y simplemente habla. Responderé en voz alta y escucharé tu siguiente pregunta.',
	tipTalk: 'Elige Hablar y simplemente habla. Responderé en voz alta y escucharé tu siguiente pregunta.',
	tipPad: 'La cruceta mueve, A selecciona, B vuelve atrás y Start abre el menú rápido.',
	tipMore: 'Toca Más para ver acciones rápidas: Lens, Scribe, Configuración y más.',
	tipKeys: 'Presiona Ctrl + K para ir a cualquier parte.',
	start: 'Empezar a usar Mimi',
	welcome: 'Te doy la bienvenida, {name}. Cuando quieras, empezamos.'
} satisfies Messages['onboarding'];
