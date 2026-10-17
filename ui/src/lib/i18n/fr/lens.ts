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
	newPhoto: 'Nouvelle photo',
	// The buttons' requests appear in the chat as the user's own words (French uses tu, as on the Map).
	promptExplain: 'Qu’y a-t-il sur cette photo\xa0? Explique-le clairement.',
	promptTranslate: 'Traduis tout le texte de cette photo en français, puis explique ce qui n’est pas clair.',
	promptIdentify: 'Qu’est-ce que c’est\xa0? Identifie-le et compare-le avec une image de référence de la bibliothèque si tu peux.',
	promptSummarize: 'Résume ce document et liste tout ce que je dois faire.',
} satisfies Messages['lens'];
