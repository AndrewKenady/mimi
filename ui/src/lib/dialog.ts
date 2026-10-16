// Modal dialog behaviour as one Svelte action, shared by every overlay:
//
//   <div class="sheet" use:dialog={{ label: 'Quick menu', onclose: () => (open = false) }}>
//
// It gives the node dialog semantics (role, aria-modal), moves focus in, keeps Tab and
// stray focus inside, closes on Escape and on the controller's Back button, and puts
// focus back where it was when the dialog goes away. Dialogs stack: only the top one
// listens. Toasts stay reachable (an Undo must work while a dialog is open).
import { focusables } from './gamepad';

export type DialogOptions = {
	/** Accessible name, when there's no visible title to point at. */
	label?: string;
	/** id of the visible title. Preferred over `label`. */
	labelledby?: string;
	describedby?: string;
	role?: 'dialog' | 'alertdialog';
	/** Escape / controller Back. Omit to make the dialog impossible to dismiss that way. */
	onclose?: () => void;
	/** Selector or element to focus first. Default: [data-autofocus], else the first control, else the dialog. */
	initialFocus?: string | HTMLElement | null;
	/** Return focus to whatever had it before. Default true. */
	restoreFocus?: boolean;
};

const stack: HTMLElement[] = [];
const ALLOWED_OUTSIDE = '[data-toasts]';

export function dialog(node: HTMLElement, options: DialogOptions = {}) {
	let opts = options;
	const previous = document.activeElement as HTMLElement | null;
	const top = () => stack[stack.length - 1] === node;

	function apply() {
		node.setAttribute('role', opts.role ?? node.getAttribute('role') ?? 'dialog');
		node.setAttribute('aria-modal', 'true');
		if (opts.labelledby) node.setAttribute('aria-labelledby', opts.labelledby);
		else if (opts.label) node.setAttribute('aria-label', opts.label);
		if (opts.describedby) node.setAttribute('aria-describedby', opts.describedby);
		if (!node.hasAttribute('tabindex')) node.tabIndex = -1;
		node.dataset.layer = ''; // the gamepad navigates only the topmost layer
	}
	apply();
	stack.push(node);

	const first = () => {
		const want = opts.initialFocus;
		const target =
			(typeof want === 'string' ? node.querySelector<HTMLElement>(want) : want) ??
			node.querySelector<HTMLElement>('[data-autofocus]') ??
			focusables(node)[0] ??
			node;
		target.focus({ preventScroll: true });
	};
	// After the enter transition has laid the node out.
	const raf = requestAnimationFrame(() => requestAnimationFrame(() => top() && !node.contains(document.activeElement) && first()));

	function onKey(e: KeyboardEvent) {
		if (!top()) return;
		if (e.key === 'Escape' && opts.onclose) {
			e.preventDefault();
			e.stopImmediatePropagation();
			opts.onclose();
		} else if (e.key === 'Tab') {
			const items = focusables(node);
			if (!items.length) return e.preventDefault();
			const i = items.indexOf(document.activeElement as HTMLElement);
			const next = e.shiftKey ? (i <= 0 ? items.length - 1 : i - 1) : i === items.length - 1 ? 0 : i + 1;
			e.preventDefault();
			items[next].focus();
		}
	}
	function onFocusIn(e: FocusEvent) {
		const t = e.target as HTMLElement;
		if (!top() || node.contains(t) || t.closest?.(ALLOWED_OUTSIDE)) return;
		first();
	}
	function onBack(e: Event) {
		if (!top() || !opts.onclose) return;
		e.preventDefault(); // stops the app-level history.back()
		e.stopImmediatePropagation();
		opts.onclose();
	}
	addEventListener('keydown', onKey, true);
	document.addEventListener('focusin', onFocusIn);
	addEventListener('mimi:back', onBack, true);

	return {
		update(next: DialogOptions) {
			opts = next;
			apply();
		},
		destroy() {
			cancelAnimationFrame(raf);
			removeEventListener('keydown', onKey, true);
			document.removeEventListener('focusin', onFocusIn);
			removeEventListener('mimi:back', onBack, true);
			const i = stack.indexOf(node);
			if (i >= 0) stack.splice(i, 1);
			const hadFocus = node.contains(document.activeElement) || document.activeElement === document.body;
			if (opts.restoreFocus !== false && hadFocus && previous?.isConnected) previous.focus({ preventScroll: true });
		}
	};
}

/** True while any dialog is open (for global shortcuts that should stand down). */
export const dialogOpen = () => stack.length > 0;
