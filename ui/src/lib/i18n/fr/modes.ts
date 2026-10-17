// Core's chat modes by id: [name, description]. Shared by the chat and Settings areas so a mode
// has one name everywhere. Unknown ids (custom modes) keep Core's own wording.
export const MODES: Record<string, [string, string]> = {
	everyday: ['Au quotidien', 'Aide générale, avec des sources quand cela compte.'],
	road_trip: ['Road trip', 'Lieux, histoire et récits au fil de la route.'],
	field_medic: ['Secouriste', 'Premiers secours et santé, appuyés sur WikiMed.'],
	fix_it: ['Dépannage', 'Réparations, bricolage et résolution de problèmes.'],
	study: ['Étude', 'Apprenez de tout : articles, conférences et livres.'],
	storyteller: ['Conteur', 'Histoires, poèmes et grands classiques.']
};
