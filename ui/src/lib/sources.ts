// Shared helpers for the sources an answer cites.
import { t } from '$lib/i18n/index.svelte';

/** Short shelf names, matching `COLLECTION_NAMES` in core/mimi/tools.py. Names stay names;
 *  the rest follow the interface language (getters, so a language change shows at once). */
export const COLLECTIONS: Record<string, string> = {
	encyclopedia: 'Wikipedia',
	medicine: 'WikiMed',
	repair: 'iFixit',
	travel: 'Wikivoyage',
	get survival() {
		return t('chat.collSurvival');
	},
	get dictionary() {
		return t('chat.collDictionary');
	},
	qa: 'Stack Exchange',
	get books() {
		return t('chat.collBook');
	},
	get talks() {
		return t('chat.collTalk');
	}
};

/** "WikiMed", "Your file", "Scribe note"… */
export function sourceLabel(s: any): string {
	if (!s) return '';
	if (s.type === 'note') return t('chat.scribeNote');
	if (s.type === 'file') return t('chat.yourFile');
	return COLLECTIONS[s.collection] || s.book_title || t('chat.library');
}
