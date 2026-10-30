import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig, type Plugin } from 'vite';

const core = 'http://127.0.0.1:7600';

// The browser demo (npm run build:demo) is the same app with a recorded Core in place of the
// real one. Everything demo-specific sits behind __MIMI_DEMO__, which is `false` in normal
// builds, so the bundler drops it: the app Mimi ships never contains a line of demo code.
declare const process: { env: Record<string, string | undefined> }; // (no @types/node here)
const DEMO = process.env.MIMI_DEMO === '1';
// The demo is served from GitHub Pages under a sub-path, and built into its own folder so it
// never mixes with the build Mimi Core serves.
const BASE = DEMO ? (process.env.MIMI_DEMO_BASE ?? '/mimi/demo') : '';
const out = DEMO ? 'build-demo' : 'build';

/**
 * Demo only: the demo is served under a sub-path (/mimi/demo), but the app navigates with
 * root-relative URLs, many of them from API data (citations, search results). Point every
 * `$app/navigation` import in src/ at a wrapper whose goto() adds the base path.
 */
function demoNavigation(): Plugin {
	const wrapper = '/src/lib/demo/navigation';
	return {
		name: 'mimi-demo-navigation',
		enforce: 'pre',
		transform(code, id) {
			const file = id.split('?')[0].replace(/\\/g, '/');
			if (!file.includes('/src/') || file.includes(wrapper) || !code.includes('$app/navigation')) return;
			return { code: code.replace(/(['"])\$app\/navigation\1/g, `$1${wrapper}.ts$1`), map: null };
		}
	};
}

export default defineConfig({
	plugins: [
		...(DEMO ? [demoNavigation()] : []),
		tailwindcss(),
		sveltekit({
			preprocess: vitePreprocess(),
			// Single-page app: MIMI Core serves index.html for every route.
			adapter: adapter({ pages: out, assets: out, fallback: 'index.html', precompress: false, strict: false }),
			// #lib and #components are subpath imports in package.json.
			...(DEMO ? { paths: { base: BASE as `/${string}`, relative: false } } : {})
		})
	],
	define: { __MIMI_DEMO__: JSON.stringify(DEMO), __MIMI_BASE__: JSON.stringify(BASE) },
	server: {
		port: 5173,
		proxy: {
			'/api/events': { target: core, ws: true },
			'/api': core,
			'/kiwix': core,
			'/maps': core,
			'/cert': core
		}
	},
	build: { target: 'es2022', chunkSizeWarningLimit: 1200 }
});
