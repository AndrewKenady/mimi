// See https://svelte.dev/docs/kit/types#app.d.ts
declare global {
	/** True only in the browser demo build (MIMI_DEMO=1); see vite.config.ts. */
	const __MIMI_DEMO__: boolean;
	namespace App {}
	interface Window {
		mimiHost?: { available: boolean; post: (msg: unknown) => void };
		chrome?: { webview?: { postMessage: (m: unknown) => void; addEventListener: (t: string, cb: (e: MessageEvent) => void) => void } };
	}
}

export {};
