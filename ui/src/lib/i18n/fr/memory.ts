import { fmtNumber, plural, type Messages } from '../index.svelte';

export default {
	pageTitle: 'Mémoire · Mimi',
	heading: 'Mémoire',
	intro: 'Ce que Mimi sait de vous, pour vous aider sans avoir à redemander. Tout reste sur cet appareil, et vous gardez la main sur chaque mot.',

	catPersonal: 'À propos de vous',
	catPreference: 'Préférences',
	catProject: 'Projets',
	catOther: 'Autres',

	settingsLabel: 'Paramètres de la mémoire',
	modeLabel: 'Mode de mémoire',
	modeAsk: 'Demander d’abord',
	modeAuto: 'Automatique',
	modeOff: 'Désactivé',
	explainAsk: 'Mimi propose des choses à retenir, et vous approuvez chacune d’elles.',
	explainAuto: 'Mimi enregistre automatiquement les informations durables. Vous pouvez les revoir ici.',
	explainOff: 'Mimi n’enregistrera ni n’utilisera de souvenirs.',
	resume: 'Reprendre la mémoire',
	pause: 'Mettre la mémoire en pause',
	export: 'Exporter',
	eraseAll: 'Tout effacer',
	pausedNote: 'La mémoire est en pause. Mimi n’utilise ni n’enregistre de souvenirs pour le moment.',

	waiting: 'En attente de votre accord',
	keep: 'Garder',
	keepItem: 'Garder : {text}',
	discard: 'Écarter',
	discardItem: 'Écarter : {text}',
	discarded: 'Suggestion écartée',

	search: 'Rechercher dans les souvenirs',
	searchPlaceholder: 'Rechercher',
	show: 'Afficher',
	all: 'Tous',
	add: 'Ajouter',
	newLabel: 'Quelque chose à retenir',
	newPlaceholder: 'p. ex. Je suis allergique à la pénicilline',
	kind: 'Type',
	save: 'Enregistrer',
	editLabel: 'Modifier le souvenir',
	cancel: 'Annuler',
	pinned: 'Épinglé',
	used: (p: { n: number }) => `utilisé ${fmtNumber(p.n)} fois`,
	fromChat: 'd’une discussion',
	unpin: 'Désépingler',
	alwaysUse: 'Toujours utiliser',
	pinItem: 'Épingler : toujours utiliser',
	edit: 'Modifier',
	editItem: 'Modifier : {text}',
	forget: 'Oublier',
	forgetItem: 'Oublier : {text}',
	forgotten: 'Oublié',
	emptyBefore: 'Aucun souvenir pour l’instant. Dites à Mimi quelque chose comme ',
	emptyExample: '« Souviens-toi que je conduis un Tacoma 2014 »',
	emptyAfter: ', ou ajoutez-en un vous-même.',

	wipeTitle: 'Effacer tous les souvenirs ?',
	wipeBody: (p: { n: number }) =>
		plural(p.n, {
			one: 'Mimi oubliera son unique souvenir vous concernant. Cette action est irréversible. Vous pouvez d’abord l’exporter.',
			other: 'Mimi oubliera ses # souvenirs vous concernant. Cette action est irréversible. Vous pouvez d’abord les exporter.'
		}),
	wipeConfirm: 'Tout effacer',
	wiped: 'Tous les souvenirs ont été effacés'
} satisfies Messages['memory'];
