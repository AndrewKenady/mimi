// Markdown → safe HTML, with inline citation pills.
import DOMPurify from 'dompurify';
import { Marked } from 'marked';

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

/** Render markdown; `maxCite` limits which [n] markers become pills. */
export function render(text: string, maxCite = 0): string {
	if (!text) return '';
	const html = md.parse(text, { async: false }) as string;
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

/** Plain text preview (strip markdown syntax). */
export function plain(text: string): string {
	return (text || '')
		.replace(/```[\s\S]*?```/g, ' ')
		.replace(/\[(\d+)\]/g, '')
		.replace(/[*_#>`]/g, '')
		.replace(/\s+/g, ' ')
		.trim();
}
