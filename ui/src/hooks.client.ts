import type { ClientInit } from '@sveltejs/kit';

// Runs once, before the router starts and before the app's first request. Only the browser
// demo build does anything here: __MIMI_DEMO__ is false otherwise, so the bundler drops the
// branch and the demo layer never ships with Mimi.
export const init: ClientInit = async () => {
	if (__MIMI_DEMO__) {
		const { installDemo } = await import('$lib/demo/install');
		await installDemo();
	}
};
