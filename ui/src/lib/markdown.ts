// Markdown → safe HTML, with inline citation pills.
import DOMPurify from 'dompurify';
import { Marked, type Token } from 'marked';

const md = new Marked({ gfm: true, breaks: false });

md.use({
	renderer: {
		link({ href, text }) {
			const safe = /^(https?:|mailto:)/.test(href || '') ? href : href?.startsWith('/') ? href : '#';
			const ext = /^https?:/.test(safe || '');
			return `<a href="${safe}"${ext ? ' data-external="1"' : ''}>${text}</a>`;
		}
	}
});

const CITE = /\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]/g;

function sanitize(html: string, maxCite: number): string {
	const clean = DOMPurify.sanitize(html, { ADD_ATTR: ['data-external', 'target'], FORBID_TAGS: ['style', 'form', 'input'] });
	if (!maxCite) return clean;
	// Replace citation markers outside <code>/<pre>/<a>.
	return clean
		.split(/(<pre[\s\S]*?<\/pre>|<code[\s\S]*?<\/code>|<a [\s\S]*?<\/a>)/g)
		.map((part, i) =>
			i % 2
				? part
				: part.replace(CITE, (m, nums: string) => {
						const list = nums
							.split(',')
							.map((s) => parseInt(s.trim(), 10))
							.filter((n) => n >= 1 && n <= maxCite);
						return list.length ? list.map((n) => `<button class="cite" data-cite="${n}" aria-label="Source ${n}">${n}</button>`).join('') : m;
					})
		)
		.join('');
}

/** Render markdown; `maxCite` limits which [n] markers become pills. */
export function render(text: string, maxCite = 0): string {
	if (!text) return '';
	return sanitize(md.parse(text, { async: false }) as string, maxCite);
}

export type Block = { key: string; html: string };

// Rendered top-level blocks, shared by every message: a finished paragraph is parsed and
// sanitized once, however many times the answer around it grows.
const blockCache = new Map<string, string>();
const CACHE_MAX = 600;

function renderToken(tok: Token, links: Record<string, any>, maxCite: number): string {
	const list = Object.assign([tok], { links }) as any;
	return sanitize(md.parser(list) as string, maxCite);
}

/**
 * Render markdown as a list of top-level blocks (paragraphs, lists, code fences…).
 *
 * While an answer streams, only its trailing block is still changing. Every block before
 * it comes from a cache, so its HTML string is identical between updates: Svelte leaves
 * that DOM alone, which keeps per-token work small and preserves the reader's text
 * selection. With `streaming`, the last block is always rendered fresh and never cached.
 */
export function renderBlocks(text: string, maxCite = 0, streaming = false): Block[] {
	if (!text) return [];
	const tokens = md.lexer(text);
	const links = tokens.links || {};
	const real = tokens.filter((t) => t.type !== 'space');
	return real.map((tok, i) => {
		const last = i === real.length - 1;
		if (streaming && last) return { key: `${i}`, html: renderToken(tok, links, maxCite) };
		const ck = `${maxCite}\u0000${tok.raw}`;
		let html = blockCache.get(ck);
		if (html === undefined) {
			html = renderToken(tok, links, maxCite);
			if (blockCache.size >= CACHE_MAX) blockCache.delete(blockCache.keys().next().value as string);
			blockCache.set(ck, html);
		}
		return { key: `${i}`, html };
	});
}

/** Plain text preview (strip markdown syntax). */
export function plain(text: string): string {
	return (text || '')
		.replace(/```[\s\S]*?```/g, ' ')
		.replace(/\[(\d+)\]/g, '')
		.replace(/[*_#>`]/g, '')
		.replace(/\s+/g, ' ')
		.trim();
}
