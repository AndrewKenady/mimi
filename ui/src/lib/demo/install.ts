// The browser demo's entry point (demo build only; see src/hooks.client.ts). Before the
// app makes its first request it: restores a deep link that GitHub Pages' 404 page bounced
// here, puts the recorded Core behind fetch() and the event socket, gives root-relative
// links the base path, and mounts the demo banner.
import { base } from '#lib/base.js';
import { mount } from 'svelte';
import { app } from '#lib/app.svelte.js';
import { i18n, t } from '#lib/i18n/index.svelte.js';
import { handle, R, S } from './core';
import { installLinks } from './links';
import { stripBase } from './paths';
import { installSocket } from './socket';
import { demo } from './state.svelte';
import DemoBanner from './DemoBanner.svelte';

const CORE = /^\/(api|kiwix|cert)(\/|$)/;

/** site/404.html sends /mimi/demo/<path> here as ?_path=<path>; put it back before the router reads the URL. */
function restoreDeepLink() {
	const u = new URL(location.href);
	const p = u.searchParams.get('_path');
	if (p === null) return;
	const target = p.startsWith('/') && !p.startsWith('//') ? p : '/';
	history.replaceState(history.state, '', base + (target === '/' ? '' : target));
}

async function bodyOf(input: RequestInfo | URL, init?: RequestInit): Promise<unknown> {
	let raw: unknown = init?.body;
	if (raw === undefined && input instanceof Request && !['GET', 'HEAD'].includes(input.method)) raw = await input.clone().text();
	if (typeof raw !== 'string' || !raw) return raw instanceof FormData ? raw : undefined;
	try {
		return JSON.parse(raw);
	} catch {
		return raw;
	}
}

/** The map's tiles, fonts and sprites are real files, published next to the demo. */
const realFetch = window.fetch.bind(window);
let tiles: Promise<ArrayBuffer> | null = null;
async function mapFile(url: URL, headers: Headers): Promise<Response> {
	const file = `${base}${url.pathname}`;
	const range = headers.get('range');
	if (!url.pathname.endsWith('.pmtiles') || !range) return realFetch(file);
	if (!tiles) {
		const r = await realFetch(file, { headers: { range } });
		if (r.status === 206 || !r.ok) return r; // the host serves byte ranges itself
		tiles = r.arrayBuffer(); // it doesn't: read the (small) file once and slice it here
	}
	const buf = await tiles;
	const m = /bytes=(\d*)-(\d*)/.exec(range);
	const start = m?.[1] ? Number(m[1]) : Math.max(0, buf.byteLength - Number(m?.[2] || 0));
	const end = Math.min(buf.byteLength - 1, m?.[1] && m?.[2] ? Number(m[2]) : buf.byteLength - 1);
	return new Response(buf.slice(start, end + 1), {
		status: 206,
		headers: { 'content-type': 'application/octet-stream', 'content-range': `bytes ${start}-${end}/${buf.byteLength}`, 'content-length': String(end - start + 1) }
	});
}

function installFetch() {
	window.fetch = async function (input: RequestInfo | URL, init?: RequestInit) {
		const url = new URL(input instanceof Request ? input.url : String(input), location.href);
		if (url.origin !== location.origin) return realFetch(input, init);
		if (url.pathname.startsWith('/maps/')) return mapFile(url, new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined)));
		if (!CORE.test(url.pathname)) return realFetch(input, init);
		if (!url.pathname.startsWith('/api/')) return new Response(t('demo.notPartShort'), { status: 404 });
		const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
		const signal = init?.signal ?? (input instanceof Request ? input.signal : undefined) ?? undefined;
		if (signal?.aborted) throw new DOMException('The user aborted a request.', 'AbortError');
		return handle({ method, url, body: await bodyOf(input, init), signal });
	};
}

/** Camera and microphone stay off: nothing in the demo would use them. Say so, once, plainly. */
const CAMERA = () => t('demo.camera');
const MIC = () => t('demo.mic');
function installMedia() {
	// What the app asked for last, and when: in Spanish or French its own toasts aren't worded as below.
	let asked = { at: -Infinity, video: false };
	const md = navigator.mediaDevices;
	if (md) {
		md.getUserMedia = async (c?: MediaStreamConstraints) => {
			asked = { at: performance.now(), video: !!c?.video };
			throw new DOMException('Not available in the browser demo', 'NotAllowedError');
		};
	}
	// The app's own "no camera / no microphone" toasts become the demo's honest version.
	const REWRITE: [RegExp, () => string][] = [
		[/^No camera available/, CAMERA],
		[/^Microphone (unavailable|permission)/i, MIC],
		[/^Could not (start|use) the microphone/i, MIC]
	];
	const toast = app.toast.bind(app);
	app.toast = (text, ...rest) => {
		const rewrite = REWRITE.find(([re]) => re.test(text))?.[1];
		// In another language: an error toast right after the camera or mic was refused is that toast.
		const refused = !rewrite && i18n.locale !== 'en' && rest[0] === 'error' && performance.now() - asked.at < 2000;
		return toast(rewrite ? rewrite() : refused ? (asked.video ? CAMERA() : MIC()) : text, ...rest);
	};
}

function trackPath() {
	const set = () => (demo.path = stripBase(location.pathname));
	for (const k of ['pushState', 'replaceState'] as const) {
		const orig = history[k].bind(history);
		history[k] = (...a: Parameters<History['pushState']>) => {
			orig(...a);
			set();
		};
	}
	addEventListener('popstate', set);
	set();
}

export async function installDemo() {
	restoreDeepLink();
	document.documentElement.classList.add('mimi-demo');
	installFetch();
	installSocket(() => {
		const b = R.get['/api/bootstrap'].body;
		return [
			{ type: 'model', data: b.models },
			{ type: 'library', data: b.health?.library ?? {} },
			{ type: 'location', data: S.location },
			...R.events.filter((e) => !['model', 'library', 'location'].includes(e.type))
		];
	});
	installMedia();
	// links.ts words its two notes in English; show them in the interface language.
	installLinks((text) => app.toast(text.startsWith('Downloads') ? t('demo.downloads') : t('demo.deviceFile'), 'info'));
	trackPath();
	try {
		if (sessionStorage.getItem('mimi.demo.signout')) {
			sessionStorage.removeItem('mimi.demo.signout');
			setTimeout(() => app.toast(t('demo.oneAccount', { name: R.get['/api/bootstrap'].body.me?.name ?? 'Ada' }), 'info'), 900);
		}
	} catch {
		/* no session storage */
	}
	const host = document.createElement('div');
	host.id = 'mimi-demo';
	document.body.prepend(host);
	mount(DemoBanner, { target: host });
}
