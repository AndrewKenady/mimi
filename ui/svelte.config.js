import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		// Single-page app: MIMI Core serves index.html for every route.
		adapter: adapter({ pages: 'build', assets: 'build', fallback: 'index.html', precompress: false, strict: false }),
		alias: { $components: 'src/lib/components' }
	}
};

export default config;
