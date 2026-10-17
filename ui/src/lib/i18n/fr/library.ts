import { fmtNumber, plural, type Messages } from '../index.svelte';

// Core's item_noun (English, singular or plural) → this language's forms.
const NOUNS: Record<string, [one: string, other: string]> = {
	article: ['article', 'articles'],
	document: ['document', 'documents'],
	talk: ['conférence', 'conférences'],
	video: ['vidéo', 'vidéos'],
	book: ['livre', 'livres'],
	page: ['page', 'pages'],
	item: ['élément', 'éléments']
};
const noun = (s: string) => NOUNS[s.replace(/s$/, '')];

// Core's collection ids (core/mimi/kiwix.py COLLECTIONS).
const COLLECTIONS: Record<string, string> = {
	medicine: 'Médecine',
	encyclopedia: 'Encyclopédie',
	travel: 'Voyage',
	repair: 'Guides de réparation',
	survival: 'Survie',
	dictionary: 'Dictionnaire',
	qa: 'Questions-réponses',
	books: 'Livres',
	talks: 'Conférences',
	courses: 'Cours',
	other: 'Autres'
};

export default {
	title: 'Bibliothèque',
	myFiles: 'Mes fichiers',
	back: 'Retour',
	clear: 'Effacer',
	loading: 'Chargement…',
	askMimi: 'Demander à Mimi',
	notFoundTitle: 'Introuvable dans la bibliothèque',
	backToLibrary: 'Retour à la bibliothèque',

	itemCount: (p: { n: number; noun: string }) => {
		const f = noun(p.noun);
		return f ? plural(p.n, { one: `# ${f[0]}`, other: `# ${f[1]}` }) : `${fmtNumber(p.n)} ${p.noun}`;
	},
	collections: (p: { n: number }) => plural(p.n, { one: '# collection', other: '# collections' }),
	pages: (p: { n: number }) => plural(p.n, { one: '# page', other: '# pages' }),
	pageN: 'page {n}',
	collection: (p: { id: string; label: string }) => COLLECTIONS[p.id] ?? p.label,

	subtitleEmpty: 'Vos ouvrages de référence, hors ligne',
	offline: 'hors ligne',
	searchPlaceholder: 'Rechercher dans tous les articles, guides et réponses…',
	all: 'Toutes',
	askAbout: 'Demander à Mimi : {q}',
	noMatches: "Aucun résultat. Essayez d'autres mots.",
	emptyTitle: 'La bibliothèque se prépare',
	emptyBody: "Les collections apparaissent ici dès qu'elles ont fini de se télécharger.",
	cantOpenBook: 'Mimi ne peut pas ouvrir ce livre.',
	statusReady: 'Prêt',
	statusIndexing: 'Indexation…',
	statusChecking: 'Vérification…',
	statusUnreadable: 'Impossible à ouvrir',
	statusBrowseOnly: 'Lecture seule',
	statusSearchOnly: 'Recherche seule',

	incompleteTitle: (p: { n: number }) => plural(p.n, { one: "# livre n'a pas fini de se télécharger", other: "# livres n'ont pas fini de se télécharger" }),
	incompleteRest: (p: { n: number }) => plural(p.n, { one: ", il n'est donc pas encore dans la bibliothèque.", other: ', ils ne sont donc pas encore dans la bibliothèque.' }),
	incompleteSize: '{done} sur {total}',
	incompleteNotBook: 'pas un fichier de livre lisible',
	incompleteHint: "Relancez votre commande d'installation, ou {cmd} pour son pack : les téléchargements reprennent là où ils se sont arrêtés.",

	collectionMissing: "Cette collection n'est pas dans la bibliothèque.",
	filterPlaceholder: (p: { noun: string }) => `Filtrer les ${noun(p.noun)?.[1] ?? p.noun} par titre ou auteur…`,
	filterNoMatch: 'Rien ne correspond à ce filtre.',
	collectionEmpty: "Mimi n'a rien trouvé à afficher dans cette collection.",
	showMore: (p: { n: number }) => `Afficher plus (encore ${fmtNumber(p.n)})`,
	typeVideo: 'Vidéo',
	typeAudio: 'Audio',
	typeImage: 'Image',
	typePage: 'Page',
	typeText: 'Texte',
	typeFile: 'Fichier',
	searchable: 'Recherche possible',
	searchIndexing: 'Préparation de la recherche…',
	notSearchable: 'Recherche impossible',

	articleNotFound: 'Article introuvable',
	externalLink: 'Ce lien mène vers Internet. La bibliothèque de Mimi fonctionne hors ligne.',
	openInNewTab: 'Ouvrir dans un nouvel onglet',
	download: 'Télécharger',
	smallerText: 'Texte plus petit',
	largerText: 'Texte plus grand',
	contents: 'Sommaire',
	cantShowTitle: 'Mimi ne peut pas afficher ce type de fichier',
	cantShowBody: "{type} s'ouvre dans une autre application. Téléchargez-le pour en garder une copie.",
	thisFile: 'Ce fichier',
	askDocument: "D'après « {title} » ({book}), quels sont les points clés ?",
	askDocumentPage: "D'après « {title} » ({book}), quels sont les points clés de la page {page} ?",
	askArticle: "D'après l'article « {title} » de la bibliothèque ({book}), quels sont les points clés ?",

	filesIntro: 'Les documents et les notes Scribe dans lesquels Mimi peut chercher quand vous posez des questions. Ils ne quittent jamais cet appareil.',
	dropFiles: 'Déposez des fichiers ici ou appuyez pour en ajouter',
	dropHint: "PDF, Word, texte, Markdown, HTML, CSV · jusqu'à 60 Mo",
	searchFiles: 'Rechercher dans vos fichiers',
	noFileMatches: 'Aucun résultat.',
	noFiles: "Aucun fichier pour l'instant.",
	addingFile: 'Ajout de « {name} » à votre bibliothèque…',
	scribeNote: 'Note Scribe',
	passages: (p: { n: number }) => plural(p.n, { one: '# passage', other: '# passages' }),
	fileReady: 'Prêt',
	fileIndexing: 'Indexation',
	fileError: 'Erreur',
	deleteFile: 'Supprimer {title}'
} satisfies Messages['library'];
