import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

// MIMI_DEMO=1 builds the browser demo (see src/lib/demo): served from GitHub Pages under a
// sub-path, into its own folder so it never mixes with the build Mimi Core serves.
const demo = process.env.MIMI_DEMO === '1';
const out = demo ? 'build-demo' : 'build';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		// Single-page app: MIMI Core serves index.html for every route.
		adapter: adapter({ pages: out, assets: out, fallback: 'index.html', precompress: false, strict: false }),
		alias: { $components: 'src/lib/components' },
		...(demo ? { paths: { base: process.env.MIMI_DEMO_BASE ?? '/mimi/demo', relative: false } } : {})
	}
};

export default config;
