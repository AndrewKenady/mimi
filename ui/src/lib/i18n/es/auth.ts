import type { Messages } from '../index.svelte';
import { plural } from '../index.svelte';

const STATUS: Record<string, string> = { approved: 'aprobada', denied: 'rechazada', expired: 'caducada', replaced: 'reemplazada' };

export default {
	welcome: 'Te damos la bienvenida a Mimi',
	welcomeSub: 'Una IA que vive por completo en este dispositivo, sin necesidad de internet.',
	howToJoin: 'Cómo entrar',
	joinAsGuest: 'Entrar como invitado',
	signIn: 'Iniciar sesión',
	yourNameOptional: 'Tu nombre (opcional)',
	name: 'Nombre',
	pinOrPassword: 'PIN o contraseña',
	noPinHint: '¿No tienes PIN? Déjalo en blanco y aprueba el acceso en el dispositivo Mimi.',
	guestNote: 'Los chats de invitado no se guardan y Mimi no te recordará.',
	guest: 'Invitado',
	oneMoment: 'Un momento…',
	continue: 'Continuar',
	askDevice: 'Preguntar al dispositivo Mimi',
	errName: 'Escribe tu nombre.',

	locked: 'Mimi está bloqueado',
	lockedSub: 'Escribe el PIN del propietario para continuar.',
	pin: 'PIN',
	unlock: 'Desbloquear',

	checkScreen: 'Mira la pantalla de Mimi',
	tapAllow: 'Toca {allow} en el dispositivo Mimi para iniciar sesión como {name}. Muestra este código:',
	code: 'Código {code}',
	waiting: 'Esperando la aprobación…',
	noScreen: 'Mimi no está abierto en la pantalla del dispositivo en este momento, así que nadie puede tocar Permitir. Abre o desbloquea Mimi allí y aparecerá esta solicitud, o cancela y usa tu PIN.',
	cancel: 'Cancelar',
	declined: 'La solicitud fue rechazada en el dispositivo Mimi.',
	timedOut: 'La solicitud caducó. Vuelve a intentarlo o usa un PIN.',

	request: 'Solicitud de inicio de sesión',
	wants: '{client} desde {ip} quiere iniciar sesión como {name}.',
	matchCode: 'Comprueba que este código coincida con el de esa pantalla',
	deny: 'Rechazar',
	allow: 'Permitir',
	pause: 'Pausar las solicitudes durante 10 minutos',
	expiresIn: 'Caduca en {s} s',
	moreWaiting: (p: { n: number }) => plural(p.n, { one: '# más en espera', other: '# más en espera' }),
	onlyKnown: 'Permite solo los dispositivos que reconozcas.',
	approved: '{client} ya puede iniciar sesión como {name}',
	denied: 'Solicitud rechazada. Ese dispositivo debe esperar 10 minutos para volver a pedirlo.',
	alreadyExpired: 'Esa solicitud ya había caducado',
	already: (p: { status: string }) => `Esa solicitud ya estaba ${STATUS[p.status] ?? p.status}`,
	expired: 'Esa solicitud caducó',
	paused: 'Solicitudes de inicio de sesión pausadas durante 10 minutos. Los PIN siguen funcionando.',
	pauseFailed: 'No se pudieron pausar las solicitudes'
} satisfies Messages['auth'];
