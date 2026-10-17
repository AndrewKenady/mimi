import type { Messages } from '../index.svelte';

export default {
	language: 'Langue',
	languageAuto: 'Automatique ({name})',
	languageHint: 'La langue des menus et des messages. Mimi répond dans la langue dans laquelle vous écrivez.'
} satisfies Messages['common'];
