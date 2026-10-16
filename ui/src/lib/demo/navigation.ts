// Demo build only: vite.config.ts points every `$app/navigation` import in src/ here. The app
// navigates with root-relative URLs ('/library', citation links from API data…); the demo is
// served under a base path, so goto() adds it. Everything else is SvelteKit's own.
import { goto as kitGoto } from '$app/navigation';
import { withBase } from './paths';

export * from '$app/navigation';

export function goto(url: string | URL, opts?: Parameters<typeof kitGoto>[1]): ReturnType<typeof kitGoto> {
	return kitGoto(typeof url === 'string' ? withBase(url) : url, opts);
}
