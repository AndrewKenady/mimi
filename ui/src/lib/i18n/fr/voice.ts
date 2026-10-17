import type { Messages } from '../index.svelte';

export default {
	dialog: 'Conversation vocale avec Mimi',
	newConversation: 'Nouvelle conversation',
	close: 'Quitter le mode vocal',

	listening: 'J’écoute…',
	transcribing: 'Transcription de vos paroles…',
	thinking: 'Je prépare une réponse…',
	tapToTalk: 'Touchez le micro pour parler',
	startingFresh: 'On repart de zéro.',
	micUnavailable: 'Le micro n’est pas disponible ici. Vous pouvez écrire à la place.',
	heardNothing: 'Je n’ai rien entendu. Touchez le micro et parlez.',
	tapAndSpeak: 'Touchez le micro et parlez.',
	didntCatch: 'Je n’ai pas compris. Voulez-vous réessayer ?',
	quoted: '« {text} »',

	doneTalking: 'J’ai fini de parler',
	interrupt: 'Interrompre et parler',
	startTalking: 'Commencer à parler',
	typeQuestion: 'Écrivez votre question',
	send: 'Envoyer',
	typeInstead: 'Écrire plutôt',

	pauseTap: 'Faites une pause quand vous avez fini, ou touchez le bouton pour envoyer',
	pausePress: 'Faites une pause quand vous avez fini, ou appuyez sur le bouton pour envoyer',
	pauseClick: 'Faites une pause quand vous avez fini, ou cliquez sur le bouton pour envoyer',
	interruptTap: 'Touchez le bouton pour interrompre',
	interruptPress: 'Appuyez sur le bouton pour interrompre',
	interruptClick: 'Cliquez sur le bouton pour interrompre',
	talkPad: 'Sélectionnez le micro avec A pour parler',
	talkClick: 'Cliquez sur le micro ou appuyez sur Espace',
	padClose: 'B pour fermer',

	fillerLookUp: 'Je vais chercher ça.',
	fillerFiles: 'Je consulte vos fichiers.',
	fillerNearby: 'Voyons ce qu’il y a à proximité.',
	fillerWhere: 'Je vérifie où nous sommes.',
	fillerRoute: 'Je calcule l’itinéraire.',
	fillerPicture: 'Je cherche une image.',
	fillerWait: 'Un instant.'
} satisfies Messages['voice'];
