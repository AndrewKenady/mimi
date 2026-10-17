import type { Messages } from '../index.svelte';
import { plural } from '../index.svelte';

const STATUS: Record<string, string> = { approved: 'approuvée', denied: 'refusée', expired: 'expirée', replaced: 'remplacée' };

export default {
	welcome: 'Bienvenue dans Mimi',
	welcomeSub: 'Une IA qui vit entièrement sur cet appareil, sans connexion Internet.',
	howToJoin: 'Comment entrer',
	joinAsGuest: 'Entrer comme invité',
	signIn: 'Se connecter',
	yourNameOptional: 'Votre prénom (facultatif)',
	name: 'Nom',
	pinOrPassword: 'Code PIN ou mot de passe',
	noPinHint: 'Pas de code PIN ? Laissez ce champ vide et approuvez sur l’appareil Mimi.',
	guestNote: 'Les discussions des invités ne sont pas enregistrées et Mimi ne se souviendra pas de vous.',
	guest: 'Invité',
	oneMoment: 'Un instant…',
	continue: 'Continuer',
	askDevice: 'Demander à l’appareil Mimi',
	errName: 'Saisissez votre nom.',

	locked: 'Mimi est verrouillé',
	lockedSub: 'Saisissez le code PIN du propriétaire pour continuer.',
	pin: 'Code PIN',
	unlock: 'Déverrouiller',

	checkScreen: 'Regardez l’écran de Mimi',
	tapAllow: 'Touchez {allow} sur l’appareil Mimi pour vous connecter en tant que {name}. Il affiche ce code :',
	code: 'Code {code}',
	waiting: 'En attente d’approbation…',
	noScreen: 'Mimi n’est pas ouvert sur l’écran de l’appareil en ce moment : personne ne peut donc toucher Autoriser. Ouvrez ou déverrouillez Mimi sur l’appareil et cette demande s’affichera, ou annulez et utilisez votre code PIN.',
	cancel: 'Annuler',
	declined: 'La demande a été refusée sur l’appareil Mimi.',
	timedOut: 'La demande a expiré. Réessayez, ou utilisez un code PIN.',

	request: 'Demande de connexion',
	wants: '{client} ({ip}) souhaite se connecter en tant que {name}.',
	matchCode: 'Vérifiez que ce code correspond à celui affiché sur cet écran',
	deny: 'Refuser',
	allow: 'Autoriser',
	pause: 'Suspendre les demandes pendant 10 minutes',
	expiresIn: 'Expire dans {s} s',
	moreWaiting: (p: { n: number }) => plural(p.n, { one: '# autre en attente', other: '# autres en attente' }),
	onlyKnown: 'N’autorisez que les appareils que vous reconnaissez.',
	approved: '{client} peut désormais se connecter en tant que {name}',
	denied: 'Demande de connexion refusée. Cet appareil devra attendre 10 minutes avant de redemander.',
	alreadyExpired: 'Cette demande avait déjà expiré',
	already: (p: { status: string }) => `Cette demande était déjà ${STATUS[p.status] ?? p.status}`,
	expired: 'Cette demande a expiré',
	paused: 'Demandes de connexion suspendues pendant 10 minutes. Les codes PIN fonctionnent toujours.',
	pauseFailed: 'Impossible de suspendre les demandes'
} satisfies Messages['auth'];
