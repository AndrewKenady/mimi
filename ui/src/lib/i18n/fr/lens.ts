import type { Messages } from '../index.svelte';

export default {
	intro: 'Visez, photographiez, comprenez. Mimi lit le texte instantanément et peut expliquer, traduire ou identifier ce que montre la photo, le tout hors ligne.',
	noCamera: 'Aucune caméra disponible. Vous pouvez importer une photo à la place.',
	readFailed: 'Impossible de lire cette image',

	cancel: 'Annuler',
	takePhoto: 'Prendre une photo',
	switchCamera: 'Changer de caméra',
	yourCapture: 'Votre photo',
	openCamera: 'Ouvrir la caméra',
	choosePhoto: 'Choisir une photo',
	examples: 'Panneaux, menus, étiquettes, documents, plantes, pièces…',

	textFound: 'Texte trouvé',
	hideBoxes: 'Masquer les cadres',
	showBoxes: 'Afficher les cadres',
	copyText: 'Copier le texte',
	reading: 'Lecture…',
	noText: 'Aucun texte détecté. Vous pouvez quand même interroger Mimi sur l’image.',
	readIn: 'Lu sur l’appareil en {ms} ms',

	askTitle: 'Questions sur cette photo',
	explain: 'Expliquer',
	translate: 'Traduire',
	identify: 'Identifier',
	summarize: 'Résumer',
	askPlaceholder: 'Posez votre question…',
	askLabel: 'Votre question sur cette photo',
	ask: 'Demander',
	newPhoto: 'Nouvelle photo'
} satisfies Messages['lens'];
