// See https://svelte.dev/docs/kit/types#app.d.ts
declare global {
	namespace App {}
	interface Window {
		mimiHost?: { available: boolean; post: (msg: unknown) => void };
		chrome?: { webview?: { postMessage: (m: unknown) => void; addEventListener: (t: string, cb: (e: MessageEvent) => void) => void } };
	}
}

export {};
