// Shared helpers for the sources an answer cites.

/** Short shelf names, matching `COLLECTION_NAMES` in core/mimi/tools.py. */
export const COLLECTIONS: Record<string, string> = {
	encyclopedia: 'Wikipedia',
	medicine: 'WikiMed',
	repair: 'iFixit',
	travel: 'Wikivoyage',
	survival: 'Survival guide',
	dictionary: 'Dictionary',
	qa: 'Stack Exchange',
	books: 'Book',
	talks: 'TED talk'
};

/** "WikiMed", "Your file", "Scribe note"… */
export function sourceLabel(s: any): string {
	if (!s) return '';
	if (s.type === 'note') return 'Scribe note';
	if (s.type === 'file') return 'Your file';
	return COLLECTIONS[s.collection] || s.book_title || 'Library';
}
