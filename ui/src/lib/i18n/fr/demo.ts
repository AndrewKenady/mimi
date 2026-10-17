import type { Messages } from '../index.svelte';
import { plural } from '../index.svelte';

export default {
	liveDemo: 'Démo en direct',
	answerPlaying: ', une réponse est en cours de lecture',
	about: 'À propos de cette démo',
	what: '— la vraie interface de Mimi, dans votre navigateur, avec des réponses enregistrées en anglais.',
	real: 'La vraie version fonctionne hors ligne, sur votre propre appareil.',
	aboutMimi: 'À propos de Mimi',
	caseStudy: 'Étude de cas',
	newTab: '(s’ouvre dans un nouvel onglet)',
	fold: 'Replier la bannière de la démo',
	foldTitle: 'Replier',
	replayFast: 'Lecture 8× plus rapide que sur l’appareil portable.',
	replayReal: 'Lecture à la vitesse réelle de l’appareil portable : d’abord les sources, puis la réponse.',
	replayRealShort: 'Vitesse réelle : les sources, puis la réponse.',
	tryMimi: 'Essayer Mimi',
	stepOf: 'Étape {n} sur {total} :',
	tourDone: 'Visite terminée. Explorez librement.',
	orTry: 'ou essayez (en anglais)',
	skipWait: 'Passer l’attente',

	tourAsk: 'Demandez en anglais comment traiter l’hypothermie',
	tourAskShort: 'Hypothermie (en anglais)',
	tourLibrary: 'Ouvrez la Medical Library',
	tourLibraryShort: 'Medical Library',
	tourDesign: 'Découvrez le système de design',
	tourDesignShort: 'Système de design',

	honest: (p: { questions: string[] }) =>
		'Cette démo rejoue des réponses enregistrées : je ne peux donc pas chercher cela ici. Essayez l’une de ces questions (les réponses enregistrées sont en anglais) :\n\n' +
		p.questions.map((q) => `- ${q}`).join('\n') +
		'\n\nSur un vrai Mimi, je chercherais dans la bibliothèque hors ligne de votre appareil et je vous répondrais en citant mes sources.',

	notHere: '{what} n’est pas disponible dans la démo du navigateur. Sur un vrai Mimi, cela fonctionne directement sur l’appareil, hors ligne.',
	importingSettings: 'L’importation des paramètres',
	signingInDevices: 'La connexion d’autres appareils',
	attachingFiles: 'L’ajout de pièces jointes',
	addingFiles: 'L’ajout de vos propres fichiers',
	speechRecognition: 'La reconnaissance vocale',
	readingAloud: 'La lecture des réponses à voix haute',
	readingPhotos: 'La lecture de photos',
	recordingNotes: 'L’enregistrement de notes',
	noModels: 'Les modèles ne tournent pas dans la démo du navigateur : les réponses ont été enregistrées sur un vrai Mimi.',
	deviceOnly: 'Cela modifie l’appareil lui-même, donc ce n’est pas inclus dans la démo du navigateur.',
	notPart: 'Cela n’est pas inclus dans la démo du navigateur.',
	notPartShort: 'Non inclus dans la démo du navigateur',
	noCollection: 'Cette collection n’est pas dans la bibliothèque.',
	noArticle: 'Cet article ne fait pas partie de la bibliothèque enregistrée de la démo du navigateur.',
	noBookPages: 'Les pages de ce livre ne sont pas incluses dans la démo du navigateur.',
	noDirections: 'Les itinéraires hors ligne ne sont pas inclus dans cette démo.',
	setLocation: 'Indiquez d’abord votre position (touchez la carte), ou connectez un GPS.',
	oneRoute: 'Cette démo contient un seul itinéraire enregistré : d’Old Faithful à {to}. Recherchez {to} pour le voir.',

	pages: (p: { n: number }) => plural(p.n, { one: '# page', other: '# pages' }),
	docTitle: 'Absent de la démo du navigateur',
	docOnReal: 'Sur un vrai Mimi, ce PDF s’ouvre ici même, hors ligne, dans le lecteur du navigateur, et une citation de l’une de ses pages mène directement à cette page.',
	docNoFiles: 'La démo ne contient pas les fichiers de {book} : il n’y a donc rien à ouvrir. La liste des documents, leur taille et leur nombre de pages ont été enregistrés sur Mimi.',

	camera: 'La caméra n’est pas utilisée dans la démo du navigateur. Sur un vrai Mimi, Lens lit les photos directement sur l’appareil.',
	mic: 'Le micro n’est pas utilisé dans la démo du navigateur. Sur un vrai Mimi, la voix et Scribe fonctionnent directement sur l’appareil.',
	oneAccount: 'La démo du navigateur n’a qu’un seul compte : votre session reste donc ouverte au nom de {name}.',
	downloads: 'Les téléchargements et les exports viennent de Mimi lui-même : ils ne sont donc pas inclus dans la démo du navigateur.',
	deviceFile: 'Ce fichier se trouve sur l’appareil : il n’est donc pas inclus dans la démo du navigateur.'
} satisfies Messages['demo'];
