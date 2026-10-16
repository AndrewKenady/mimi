// The app's links are root-relative (<a href="/library">, links in answers and search
// results). Under the demo's base path those would leave the app, so every such href gets
// the base, as it appears in the DOM and again at click time, before SvelteKit's router
// reads it. Links to Core itself (downloads, exports) can't work here and say so.
import { withBase } from './paths';

const CORE = /^\/(api|kiwix|maps|cert)(\/|$)/;

function fix(a: Element) {
	const href = a.getAttribute('href');
	if (!href || !href.startsWith('/') || href.startsWith('//') || CORE.test(href)) return;
	const based = withBase(href);
	if (based !== href) a.setAttribute('href', based);
}

function sweep(root: ParentNode) {
	if (root instanceof Element && root.matches('a[href]')) fix(root);
	root.querySelectorAll?.('a[href]').forEach(fix);
}

export function installLinks(notHere: (text: string) => void) {
	const mo = new MutationObserver((records) => {
		for (const r of records) {
			if (r.type === 'attributes') fix(r.target as Element);
			else r.addedNodes.forEach((n) => n.nodeType === 1 && sweep(n as Element));
		}
	});
	const start = () => {
		sweep(document.body);
		mo.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['href'] });
	};
	if (document.body) start();
	else addEventListener('DOMContentLoaded', start, { once: true });

	// Capture phase: runs before SvelteKit's own click handling and the browser's default.
	addEventListener(
		'click',
		(e) => {
			const a = (e.target as Element | null)?.closest?.('a[href]');
			if (!a) return;
			const href = a.getAttribute('href')!;
			if (CORE.test(href)) {
				e.preventDefault();
				notHere(a.hasAttribute('download') ? "Downloads and exports come from Mimi itself, so they aren't part of the browser demo." : "That file lives on the device, so it isn't part of the browser demo.");
				return;
			}
			fix(a);
		},
		true
	);
}
