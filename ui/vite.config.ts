import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

const core = 'http://127.0.0.1:7600';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
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
