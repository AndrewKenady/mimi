import type { Messages } from '../index.svelte';

export default {
	back: 'Retour',
	step: 'Étape {n} sur {total}',
	continue: 'Continuer',

	hello: 'Bonjour. Je suis Mimi.',
	tagline: 'L’intelligence artificielle, sans Internet.',
	livesHere: 'Tout ce que je sais se trouve ici même, sur cet appareil.',
	begin: 'Commençons',

	nameTitle: 'Comment dois-je vous appeler ?',
	nameSub: 'Vous serez propriétaire de ce Mimi. D’autres personnes pourront le rejoindre plus tard comme invités ou utilisateurs.',
	yourName: 'Votre prénom',
	setPin: 'Définir un code PIN',
	setPinNote: 'Nécessaire pour vous connecter depuis votre téléphone ou votre ordinateur portable. Il protège aussi vos paramètres et votre mémoire.',
	pinLabel: 'Code PIN (4 à 8 chiffres)',
	settingUp: 'Configuration…',
	errName: 'Indiquez-moi votre prénom.',
	errPin: 'Un code PIN compte de 4 à 8 chiffres.',

	lookTitle: 'À votre goût',
	lookSub: 'Choisissez un style. Vous pourrez tout modifier plus tard dans les Paramètres.',
	theme: 'Thème',
	accent: 'Couleur d’accent',

	voiceTitle: 'Choisissez ma voix',
	voiceSub: 'Voici comment je parlerai quand nous discuterons. Choisissez-en une pour écouter un extrait.',
	voice: 'Voix',
	americanEnglish: 'Anglais américain',
	sample: 'Bonjour {name}, je suis Mimi. Tout ce que je sais se trouve ici même, sur cet appareil.',
	sampleNoName: 'Bonjour, je suis Mimi. Tout ce que je sais se trouve ici même, sur cet appareil.',

	memoryTitle: 'Comment dois-je me souvenir des choses ?',
	memorySub: 'Les souvenirs restent sur cet appareil. Vous pouvez tous les voir, les modifier ou les effacer.',
	memory: 'Mémoire',
	memoryAsk: 'Me demander d’abord',
	memoryAskNote: 'Je vous propose des souvenirs et vous les approuvez. Recommandé.',
	memoryAuto: 'Mémoriser automatiquement',
	memoryAutoNote: 'J’enregistre les faits durables au fil de nos échanges. Vous pouvez les revoir à tout moment.',
	memoryOff: 'Ne rien mémoriser',
	memoryOffNote: 'Chaque conversation repart de zéro.',

	doneTitle: 'Tout est prêt, {name}.',
	tipAsk: 'Posez n’importe quelle question. Je chercherai dans la bibliothèque hors ligne et je vous montrerai mes sources.',
	tipTalkTap: 'Touchez Parler et parlez, tout simplement. Je répondrai à voix haute et j’écouterai votre question suivante.',
	tipTalk: 'Choisissez Parler et parlez, tout simplement. Je répondrai à voix haute et j’écouterai votre question suivante.',
	tipPad: 'La croix directionnelle déplace, A sélectionne, B revient en arrière, Start ouvre le menu rapide.',
	tipMore: 'Touchez Plus pour les actions rapides : Lens, Scribe, Paramètres et plus encore.',
	tipKeys: 'Appuyez sur Ctrl + K pour aller n’importe où.',
	start: 'Commencer avec Mimi',
	welcome: 'Bienvenue, {name}. Je vous écoute quand vous voulez.'
} satisfies Messages['onboarding'];
