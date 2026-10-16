// The browser demo's own UI state: replay speed, the guided tour, the banner. Per-viewer
// conveniences only, so plain localStorage (wrapped: it can be missing or throw).

export function read(k: string): string | null {
	try {
		return localStorage.getItem(k);
	} catch {
		return null;
	}
}
export function write(k: string, v: string | null) {
	try {
		if (v === null) localStorage.removeItem(k);
		else localStorage.setItem(k, v);
	} catch {
		/* private window, blocked storage: the demo still works, it just forgets */
	}
}

function list(s: string | null): string[] {
	try {
		const v = JSON.parse(s || '[]');
		return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : [];
	} catch {
		return [];
	}
}

/** How much faster than the handheld "Skip the wait" replays an answer. */
export const FAST = 8;

export type Step = { id: string; label: string; short: string; done: (path: string) => boolean };

class DemoState {
	/** Replay recorded answers 8× faster than the reference handheld. */
	fast = $state(read('mimi.demo.fast') === '1');
	/** The banner is folded into a small pill. */
	folded = $state(read('mimi.demo.banner') === 'pill');
	/** Ids of guided-tour steps the visitor has done. */
	done = $state<string[]>(list(read('mimi.demo.tour')));
	/** A recorded answer is playing. */
	playing = $state(false);
	/** The app's own path (without the demo's base path). */
	path = $state('/');

	speed() {
		return this.fast ? FAST : 1;
	}
	setFast(on: boolean) {
		this.fast = on;
		write('mimi.demo.fast', on ? '1' : null);
	}
	setFolded(on: boolean) {
		this.folded = on;
		write('mimi.demo.banner', on ? 'pill' : null);
	}
	complete(id: string) {
		if (this.done.includes(id)) return;
		this.done = [...this.done, id];
		write('mimi.demo.tour', JSON.stringify(this.done));
	}
}

export const demo = new DemoState();
