// Gamepad support: spatial navigation with the D-pad / left stick, and
// configurable button actions (see Settings → Controls).
import { goto } from '$app/navigation';
import { app } from './app.svelte';

const BUTTONS = ['A', 'B', 'X', 'Y', 'LB', 'RB', 'LT', 'RT', 'Back', 'Start', 'LS', 'RS', 'Up', 'Down', 'Left', 'Right', 'Guide'];
export const SURFACES = ['/', '/chat', '/library', '/map', '/scribe', '/lens', '/memory', '/settings'];

type Dir = 'up' | 'down' | 'left' | 'right';

function visible(el: HTMLElement): boolean {
	const r = el.getBoundingClientRect();
	if (r.width < 2 || r.height < 2) return false;
	if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) return false;
	const st = getComputedStyle(el);
	return st.visibility !== 'hidden' && st.display !== 'none' && !el.closest('[inert],[aria-hidden="true"]');
}

function layer(): ParentNode {
	const layers = document.querySelectorAll<HTMLElement>('[data-layer]');
	return layers.length ? layers[layers.length - 1] : document;
}

export function focusables(root: ParentNode = layer()): HTMLElement[] {
	const sel = 'button:not([disabled]), a[href], input:not([disabled]):not([type=hidden]), textarea:not([disabled]), select, [tabindex]:not([tabindex="-1"]), [data-nav]';
	return [...root.querySelectorAll<HTMLElement>(sel)].filter(visible);
}

export function moveFocus(dir: Dir) {
	const items = focusables();
	if (!items.length) return;
	const cur = document.activeElement as HTMLElement | null;
	if (!cur || !items.includes(cur)) {
		(items.find((i) => i.dataset.autofocus !== undefined) || items[0]).focus();
		return;
	}
	const a = cur.getBoundingClientRect();
	const ax = a.left + a.width / 2;
	const ay = a.top + a.height / 2;
	let best: HTMLElement | null = null;
	let bestScore = Infinity;
	for (const el of items) {
		if (el === cur) continue;
		const b = el.getBoundingClientRect();
		const bx = b.left + b.width / 2;
		const by = b.top + b.height / 2;
		const dx = bx - ax;
		const dy = by - ay;
		const along = dir === 'left' ? -dx : dir === 'right' ? dx : dir === 'up' ? -dy : dy;
		if (along <= 4) continue;
		const across = dir === 'left' || dir === 'right' ? Math.abs(dy) : Math.abs(dx);
		// Prefer items overlapping on the cross axis.
		const overlap =
			dir === 'left' || dir === 'right' ? Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)) : Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
		const score = along + across * 2.2 - overlap * 0.8;
		if (score < bestScore) {
			bestScore = score;
			best = el;
		}
	}
	if (best) {
		best.focus({ preventScroll: true });
		best.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' });
	} else {
		// Nothing further that way: scroll the nearest scroller instead.
		const scroller = cur.closest('.page, [data-scroll]') as HTMLElement | null;
		scroller?.scrollBy({ top: dir === 'down' ? 240 : dir === 'up' ? -240 : 0, behavior: 'smooth' });
	}
}

function currentSurfaceIndex(): number {
	const p = location.pathname;
	let idx = 0;
	SURFACES.forEach((s, i) => {
		if (s === '/' ? p === '/' : p.startsWith(s)) idx = i;
	});
	return idx;
}

export function runAction(action: string, pressed = true) {
	switch (action) {
		case 'select':
			if (pressed) (document.activeElement as HTMLElement | null)?.click();
			break;
		case 'back':
			if (!pressed) return;
			if (window.dispatchEvent(new CustomEvent('mimi:back', { cancelable: true }))) history.back();
			break;
		case 'voice':
			if (pressed) app.voice = !app.voice;
			break;
		case 'lens':
			if (pressed) goto('/lens');
			break;
		case 'prev_surface':
		case 'next_surface':
			if (pressed) {
				const i = currentSurfaceIndex() + (action === 'next_surface' ? 1 : -1);
				goto(SURFACES[(i + SURFACES.length) % SURFACES.length]);
			}
			break;
		case 'push_to_talk':
			window.dispatchEvent(new CustomEvent(pressed ? 'mimi:ptt-down' : 'mimi:ptt-up'));
			break;
		case 'quick_menu':
			if (pressed) app.quick = !app.quick;
			break;
		case 'command_palette':
			if (pressed) app.palette = !app.palette;
			break;
	}
}

export function startGamepad() {
	let prev: boolean[] = [];
	let repeatAt = 0;
	let heldDir: Dir | null = null;

	const loop = () => {
		requestAnimationFrame(loop);
		if (app.settings.device?.controls?.gamepad === false) return;
		const pads = navigator.getGamepads?.() || [];
		const gp = [...pads].find((p) => p && p.connected);
		if (!gp) return;
		const now = performance.now();
		const pressed = gp.buttons.map((b, i) => (i === 6 || i === 7 ? b.value > 0.35 : b.pressed));
		const mapping: Record<string, string> = app.settings.device?.controls?.mapping || {};

		// Direction from D-pad or left stick (with auto-repeat)
		const ax = gp.axes[0] || 0;
		const ay = gp.axes[1] || 0;
		let dir: Dir | null = null;
		if (pressed[12] || ay < -0.6) dir = 'up';
		else if (pressed[13] || ay > 0.6) dir = 'down';
		else if (pressed[14] || ax < -0.6) dir = 'left';
		else if (pressed[15] || ax > 0.6) dir = 'right';
		if (dir) {
			if (dir !== heldDir || now > repeatAt) {
				markPad();
				moveFocus(dir);
				repeatAt = now + (dir === heldDir ? 110 : 380);
				heldDir = dir;
			}
		} else heldDir = null;

		// Right stick scrolls
		const ry = gp.axes[3] || 0;
		if (Math.abs(ry) > 0.25) {
			const el = (document.activeElement?.closest('.page, [data-scroll]') as HTMLElement) || document.querySelector('.page');
			el?.scrollBy({ top: ry * 18 });
		}

		pressed.forEach((isDown, i) => {
			if (i >= 12 && i <= 15) return;
			const was = prev[i] || false;
			if (isDown === was) return;
			const name = BUTTONS[i];
			const action = mapping[name] || (name === 'Guide' ? 'quick_menu' : '');
			if (!action) return;
			markPad();
			if (action === 'push_to_talk') runAction(action, isDown);
			else if (isDown) runAction(action, true);
		});
		prev = pressed;
	};
	requestAnimationFrame(loop);
}

function markPad() {
	if (app.input !== 'pad') {
		app.input = 'pad';
		document.documentElement.dataset.input = 'pad';
	}
}
