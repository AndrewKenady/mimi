// Base-path helpers for the browser demo (served at e.g. /mimi/demo instead of /).
import { base } from '#lib/base.js';

/** Paths that belong to the (recorded) Core, not to the app's pages. */
const CORE = /^\/(api|kiwix|maps|cert)(\/|$)/;

/** '/library' -> '/mimi/demo/library'. Leaves external, hash, protocol-relative, Core and already-based URLs alone. */
export function withBase(url: string): string {
	if (!base || !url.startsWith('/') || url.startsWith('//') || CORE.test(url)) return url;
	if (url === base || url.startsWith(base + '/') || url.startsWith(base + '?') || url.startsWith(base + '#')) return url;
	return url === '/' ? base : base + url;
}

/** '/mimi/demo/library' -> '/library' (the app's own idea of where it is). */
export function stripBase(path: string): string {
	if (base && (path === base || path.startsWith(base + '/'))) return path.slice(base.length) || '/';
	return path;
}
