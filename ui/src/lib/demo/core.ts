// A stand-in for Mimi Core, for the browser demo. It answers the app's HTTP requests from
// recorded.json (recorded from the real Core by ui/demo/capture.py) and keeps what the
// visitor changes (settings, chats, memories, location) for the session, so the interface
// behaves like the real thing. Anything that needs a device (models, microphone, camera,
// files) says so plainly instead of pretending.
import recordedJson from './recorded.json';
import { replay, stopReplay, type Turn } from './replay';
import { emit } from './socket';
import { demo } from './state.svelte';

type Rec = { status: number; type: string; ms: number; body: any };
export type Recorded = {
	version: number;
	captured: string;
	get: Record<string, Rec>;
	chats: Turn[];
	searches: string[];
	route?: { to: { lat: number; lon: number; name: string }; status: number; body: any };
	events: { type: string; data: any }[];
};

export const R = recordedJson as unknown as Recorded;

/** The lookup key for a request: decoded path plus sorted query, as capture.py writes them. */
export function keyOf(u: URL): string {
	const q = [...u.searchParams.entries()].sort(([a, x], [b, y]) => (a < b ? -1 : a > b ? 1 : x < y ? -1 : x > y ? 1 : 0));
	return safeDecode(u.pathname) + (q.length ? '?' + new URLSearchParams(q).toString() : '');
}
function safeDecode(s: string) {
	try {
		return decodeURIComponent(s);
	} catch {
		return s;
	}
}
const RECORDED = new Map<string, Rec>();
for (const [k, v] of Object.entries(R.get)) RECORDED.set(keyOf(new URL(k, 'http://x')), v);
const rec = (path: string) => RECORDED.get(keyOf(new URL(path, 'http://x')));
const body = (path: string) => structuredClone(rec(path)?.body);

// ---- session state ---------------------------------------------------------------------
type Chat = { id: string; title: string; project: string | null; mode: string; pinned: number; archived: number; created_at: number; updated_at: number; messages: any[]; [k: string]: any };
type State = { settings: { device: any; user: any }; chats: Chat[]; memories: any[]; location: any; users: any[] };

const KEY = 'mimi.demo.core';
const boot = () => R.get['/api/bootstrap'].body;
function fresh(): State {
	return {
		settings: structuredClone(boot().settings),
		chats: [],
		memories: body('/api/memories')?.memories ?? [],
		location: body('/api/location') ?? null,
		users: body('/api/users') ?? []
	};
}
export const S: State = (() => {
	try {
		const s = JSON.parse(sessionStorage.getItem(KEY) || 'null');
		if (s?.settings && Array.isArray(s.chats)) return { ...fresh(), ...s };
	} catch {
		/* no storage: start fresh */
	}
	return fresh();
})();
let saveTimer: ReturnType<typeof setTimeout> | undefined;
export function save() {
	clearTimeout(saveTimer);
	saveTimer = setTimeout(() => {
		try {
			sessionStorage.setItem(KEY, JSON.stringify(S));
		} catch {
			/* storage full or blocked: the session just won't survive a reload */
		}
	}, 50);
}

const now = () => Date.now() / 1000;
export const newId = (prefix: string) => prefix + Array.from(crypto.getRandomValues(new Uint8Array(8)), (b) => b.toString(16).padStart(2, '0')).join('');

// ---- responses ---------------------------------------------------------------------------
export const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'content-type': 'application/json' } });
const fail = (status: number, detail: string) => json({ detail }, status);
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
/** Device-only features answer honestly; the app shows `detail` in a toast. */
const NOT_HERE = (what: string) => fail(503, `${what} isn't available in the browser demo. On a real Mimi it runs on the device itself, offline.`);

async function replayRecord(r: Rec): Promise<Response> {
	// Keep the recorded latency (library search reads the disk for ~1 s on the handheld).
	await wait(Math.min(r.ms, 1500) / demo.speed() + 15);
	const data = structuredClone(r.body);
	if (typeof data === 'string') return new Response(data, { status: r.status, headers: { 'content-type': r.type || 'text/plain' } });
	return json(data, r.status);
}

// ---- library helpers ------------------------------------------------------------------
type Article = { book: string; alias: string; book_title: string; title: string; path: string; html: string; image: string | null };
const articles: Article[] = Object.entries(R.get)
	.filter(([k, v]) => k.startsWith('/api/library/article/') && v.status === 200 && v.body?.html)
	.map(([, v]) => v.body);
const plain = (html: string) => html.replace(/<h2[^>]*>.*?<\/h2>/g, ' ').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
const books = () => (rec('/api/library/books?all=true') ?? rec('/api/library/books'))?.body?.books ?? [];
const collections = () =>
	Object.entries(R.get)
		.filter(([k, v]) => k.startsWith('/api/library/collection/') && v.status === 200)
		.map(([, v]) => v.body);
let discoverAt = 0;

function findDoc(alias: string, path: string) {
	const c = collections().find((x) => x.book?.alias === alias || x.book?.name === alias);
	const item = c?.items?.find((d: any) => d.path === path || safeDecode(d.url || '').endsWith('/' + path));
	return item ? { c, item } : null;
}

/** Documents (PDFs) aren't shipped with the demo: say so in the reader instead of a broken frame. */
function docNote(c: any, d: any) {
	const esc = (s: string) => s.replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[ch]!);
	const mb = d.size ? `${Math.round(d.size / 1048576)} MB` : '';
	const facts = [d.author, d.pages ? `${d.pages.toLocaleString('en-US')} pages` : '', mb].filter(Boolean).map(esc).join(' · ');
	return {
		kind: 'article',
		title: d.title,
		book: c.book.name,
		alias: c.book.alias,
		book_title: c.book.title,
		path: d.path,
		image: null,
		toc: [],
		html:
			(facts ? `<p><em>${facts}</em></p>` : '') +
			(d.description ? `<p>${esc(d.description)}.</p>` : '') +
			`<h2 id="in-the-demo">Not in the browser demo</h2>` +
			`<p>On a real Mimi this PDF opens right here, offline, in the browser’s own viewer, and a citation to one of its pages jumps straight to that page.</p>` +
			`<p>The demo doesn’t carry the ${esc(c.book.title)}’s files, so there is nothing to open. The list of documents, their sizes and page counts are recorded from Mimi.</p>`
	};
}

function localSearch(q: string, limit: number) {
	const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
	const hit = (s: string) => terms.every((t) => s.toLowerCase().includes(t));
	const out: any[] = [];
	for (const a of articles) {
		const text = plain(a.html);
		if (hit(`${a.title} ${text}`))
			out.push({ title: a.title, path: a.path, book: a.book, book_title: a.book_title, collection: books().find((b: any) => b.name === a.book)?.collection, snippet: text.slice(0, 160), words: 0, score: 0, page: 0, label: '', url: `/library/read/${a.book}/${a.path}` });
	}
	for (const c of collections())
		for (const d of c.items || [])
			if (hit(`${d.title} ${d.author || ''} ${d.description || ''}`))
				out.push({ title: d.title, path: d.path, book: c.book.name, book_title: c.book.title, collection: c.book.collection, snippet: d.description || d.author || '', words: 0, score: 0, page: 0, label: '', url: d.url });
	return out.slice(0, limit);
}

// ---- chats ----------------------------------------------------------------------------------
const row = (c: Chat) => {
	const { messages, ...rest } = c;
	const last = [...messages].reverse().find((m) => m.role === 'assistant');
	return { ...rest, preview: (last?.content || '').replace(/[*#`[\]0-9]+/g, '').replace(/\s+/g, ' ').trim().slice(0, 120) };
};
export function chatById(id: string) {
	return S.chats.find((c) => c.id === id);
}
export function newChat(title = '', mode = 'everyday'): Chat {
	const t = now();
	const c: Chat = { id: newId('c_'), user_id: boot().me?.id, title, project: null, mode, head_id: null, pinned: 0, archived: 0, temporary: 0, created_at: t, updated_at: t, messages: [] };
	S.chats.unshift(c);
	save();
	return c;
}
export function touchChat(c: Chat) {
	c.updated_at = now();
	save();
	emit('chat.updated', { id: c.id });
}

// ---- the router ---------------------------------------------------------------------------
type Req = { method: string; url: URL; body: any; signal?: AbortSignal };
type Handler = (m: RegExpMatchArray, r: Req) => Response | Promise<Response>;
const routes: [string, RegExp, Handler][] = [];
const on = (method: string, re: RegExp, h: Handler) => routes.push([method, re, h]);

on('GET', /^\/api\/bootstrap$/, () => json({ ...structuredClone(boot()), settings: S.settings, location: S.location }));
on('GET', /^\/api\/settings$/, () => json(S.settings));
on('PATCH', /^\/api\/settings\/(device|user)\/([\w-]+)$/, ([, scope, section], r) => {
	const s = S.settings as any;
	s[scope] = { ...s[scope], [section]: { ...(s[scope]?.[section] || {}), ...(r.body || {}) } };
	save();
	return json(s[scope][section]);
});
on('POST', /^\/api\/settings\/(device|user)\/([\w-]+)\/reset$/, ([, scope, section]) => {
	const s = S.settings as any;
	s[scope] = { ...s[scope], [section]: structuredClone((boot().settings as any)[scope]?.[section] ?? {}) };
	save();
	return json(s[scope][section]);
});
on('GET', /^\/api\/settings\/export$/, () => json({ ...(body('/api/settings/export') || {}), ...S.settings }));
on('POST', /^\/api\/settings\/import$/, () => NOT_HERE('Importing settings'));

// chats
on('GET', /^\/api\/chats$/, (_, r) => {
	const q = (r.url.searchParams.get('q') || '').toLowerCase();
	const archived = r.url.searchParams.get('archived') === 'true';
	const project = r.url.searchParams.get('project');
	const list = S.chats
		.filter((c) => !!c.archived === archived && (!project || c.project === project))
		.filter((c) => !q || c.title.toLowerCase().includes(q) || c.messages.some((m) => (m.content || '').toLowerCase().includes(q)))
		.sort((a, b) => b.pinned - a.pinned || b.updated_at - a.updated_at);
	const projects = [...new Set(S.chats.filter((c) => !c.archived && c.project).map((c) => c.project as string))].sort();
	return json({ chats: list.map(row), projects });
});
on('POST', /^\/api\/chats$/, (_, r) => json(row(newChat(r.body?.title || '', r.body?.mode || 'everyday'))));
on('DELETE', /^\/api\/chats$/, () => {
	const n = S.chats.length;
	S.chats.length = 0;
	save();
	emit('chat.updated', {});
	return json({ deleted: n });
});
on('GET', /^\/api\/chats\/([^/]+)$/, ([, id]) => {
	const c = chatById(id);
	return c ? json(c) : fail(404, 'Chat not found');
});
on('PATCH', /^\/api\/chats\/([^/]+)$/, ([, id], r) => {
	const c = chatById(id);
	if (!c) return fail(404, 'Chat not found');
	const b = r.body || {};
	if (typeof b.title === 'string') c.title = b.title;
	if (typeof b.pinned === 'boolean') c.pinned = +b.pinned;
	if (typeof b.archived === 'boolean') c.archived = +b.archived;
	if (typeof b.project === 'string') c.project = b.project || null;
	touchChat(c);
	return json(row(c));
});
on('DELETE', /^\/api\/chats\/([^/]+)$/, ([, id]) => {
	const i = S.chats.findIndex((c) => c.id === id);
	if (i >= 0) S.chats.splice(i, 1);
	save();
	emit('chat.updated', { id });
	return json({ ok: i >= 0 });
});
on('POST', /^\/api\/chats\/([^/]+)\/head$/, ([, id]) => {
	const c = chatById(id);
	return c ? json(c) : fail(404, 'Chat not found');
});
on('POST', /^\/api\/chats\/([^/]+)\/stop$/, ([, id]) => json({ stopped: stopReplay(id) }));
on('POST', /^\/api\/chats\/([^/]+)\/messages$/, ([, id], r) => replay(id, r.body || {}, r.signal));
on('GET', /^\/api\/chats\/([^/]+)\/export$/, ([, id]) => {
	const c = chatById(id);
	if (!c) return fail(404, 'Chat not found');
	const md = `# ${c.title || 'Chat'}\n\n` + c.messages.map((m) => `**${m.role === 'user' ? 'You' : 'Mimi'}:** ${m.content}`).join('\n\n');
	return new Response(md, { headers: { 'content-type': 'text/markdown' } });
});

// memories
on('GET', /^\/api\/memories$/, (_, r) => {
	const q = (r.url.searchParams.get('q') || '').toLowerCase();
	const status = r.url.searchParams.get('status');
	const list = S.memories
		.filter((m) => (!q || m.text.toLowerCase().includes(q)) && (!status || m.status === status))
		.sort((a, b) => b.pinned - a.pinned || b.updated_at - a.updated_at);
	return json({ memories: list, mode: S.settings.user?.privacy?.memory ?? 'ask', paused: !!S.settings.user?.privacy?.memory_paused });
});
const memChanged = (m: any) => {
	save();
	emit('memory.changed', { id: m?.id, status: m?.status });
};
on('POST', /^\/api\/memories$/, (_, r) => {
	const text = String(r.body?.text || '').trim();
	if (!text) return fail(400, 'Memory text is empty');
	const t = now();
	const m = { id: newId('m_'), text, category: r.body?.category || 'other', status: 'active', pinned: +!!r.body?.pinned, source_chat_id: null, created_at: t, updated_at: t, last_used_at: null, use_count: 0 };
	S.memories.unshift(m);
	memChanged(m);
	return json(m);
});
on('PATCH', /^\/api\/memories\/([^/]+)$/, ([, id], r) => {
	const m = S.memories.find((x) => x.id === id);
	if (!m) return fail(404, 'Not Found');
	const b = r.body || {};
	if (typeof b.text === 'string') m.text = b.text;
	if (typeof b.category === 'string') m.category = b.category;
	if (typeof b.pinned === 'boolean') m.pinned = +b.pinned;
	if (typeof b.status === 'string') m.status = b.status;
	m.updated_at = now();
	memChanged(m);
	return json(m);
});
on('POST', /^\/api\/memories\/([^/]+)\/accept$/, ([, id]) => {
	const m = S.memories.find((x) => x.id === id);
	if (!m) return fail(404, 'Not Found');
	m.status = 'active';
	m.updated_at = now();
	memChanged(m);
	return json(m);
});
on('DELETE', /^\/api\/memories\/([^/]+)$/, ([, id]) => {
	const i = S.memories.findIndex((x) => x.id === id);
	if (i >= 0) S.memories.splice(i, 1);
	memChanged({ id });
	return json({ ok: i >= 0 });
});
on('DELETE', /^\/api\/memories$/, () => {
	const n = S.memories.length;
	S.memories.length = 0;
	memChanged(null);
	return json({ deleted: n });
});

// library
on('GET', /^\/api\/library\/collection\/([^/]+)$/, ([, b], r) => {
	const base = body(`/api/library/collection/${b}?offset=0&limit=120`);
	if (!base) return fail(404, 'This collection is not in the library.');
	const q = (r.url.searchParams.get('q') || '').trim().toLowerCase();
	const items = (base.items || []).filter((d: any) => !q || `${d.title} ${d.author || ''} ${d.description || ''}`.toLowerCase().includes(q));
	const offset = Number(r.url.searchParams.get('offset') || 0);
	const limit = Number(r.url.searchParams.get('limit') || 120);
	return json({ ...base, total: items.length, items: items.slice(offset, offset + limit) });
});
on('GET', /^\/api\/library\/article\/([^/]+)\/(.*)$/, async ([, book, path], r) => {
	const hit = rec(r.url.pathname);
	if (hit && hit.status === 200) return replayRecord(hit);
	const bk = safeDecode(book);
	const p = safeDecode(path);
	const doc = findDoc(bk, p);
	if (doc) return json(docNote(doc.c, doc.item));
	// same article, reached through another book's path (e.g. a main-page redirect)
	const title = p.split('/').pop()!.replace(/_/g, ' ');
	const a = articles.find((x) => x.title === title);
	if (a) return json(a);
	return fail(404, "That article isn't part of the browser demo's recorded library.");
});
on('GET', /^\/api\/library\/home\/([^/]+)$/, ([, alias]) => {
	const b = books().find((x: any) => x.alias === alias || x.name === alias);
	if (!b) return fail(404, 'Not Found');
	if (b.kind && b.kind !== 'articles') return json({ book: b.alias, path: '', kind: b.kind });
	const a = articles.find((x) => x.book === b.name || x.alias === b.alias);
	return a ? json({ book: b.alias, path: a.path, kind: 'articles' }) : fail(404, "That book's pages aren't part of the browser demo.");
});
on('GET', /^\/api\/library\/random$/, () => {
	const r0 = rec('/api/library/random');
	if (r0?.status === 200) return json(r0.body);
	// The fixture library has no long illustrated reads; take turns with the recorded articles.
	const pool = articles.filter((a) => a.image);
	const a = (pool.length ? pool : articles)[discoverAt++ % Math.max(1, (pool.length ? pool : articles).length)];
	if (!a) return fail(404, 'Not Found');
	return json({ book: a.alias || a.book, book_title: a.book_title, path: a.path, title: a.title, image: a.image, excerpt: plain(a.html).slice(0, 300) });
});
on('GET', /^\/api\/library\/search$/, async (_, r) => {
	const q = (r.url.searchParams.get('q') || '').trim();
	const limit = Number(r.url.searchParams.get('limit') || 12);
	const exact = rec(`/api/library/search?limit=16&q=${encodeURIComponent(q.toLowerCase())}`);
	if (exact && !r.url.searchParams.get('collection')) return replayRecord(exact);
	await wait(600 / demo.speed());
	return json({ results: localSearch(q, limit) });
});
on('GET', /^\/api\/library\/suggest$/, () => json({ results: [] }));

// location & maps
on('GET', /^\/api\/location$/, () => json(S.location));
on('POST', /^\/api\/location$/, (_, r) => {
	const { lat, lon, label, manual } = r.body || {};
	if (typeof lat !== 'number' || typeof lon !== 'number') return fail(422, 'Invalid coordinates');
	const near = S.location?.current && Math.abs(S.location.current.lat - lat) < 1e-4 && Math.abs(S.location.current.lon - lon) < 1e-4;
	if (!near) {
		S.location = { ...(S.location || {}), current: { lat, lon, source: manual ? 'manual' : 'device', label: label || null, accuracy: r.body?.accuracy ?? null }, description: label ? { name: label, text: label } : null };
		save();
	}
	emit('location', S.location);
	return json(S.location);
});
on('DELETE', /^\/api\/location\/(manual|live)$/, ([, which]) => {
	if (which === 'manual') {
		S.location = { ...(S.location || {}), current: null, description: null };
		save();
		emit('location', S.location);
	}
	return json(S.location);
});
on('GET', /^\/api\/location\/nearby$/, (_, r) => {
	const exact = rec(r.url.pathname + r.url.search);
	if (exact) return replayRecord(exact);
	// The map asks around wherever it's centred; answer with what was recorded around the pin.
	const kind = r.url.searchParams.get('kind') || 'all';
	const lim = Number(r.url.searchParams.get('limit') || 24);
	const near = Object.entries(R.get).find(([k]) => k.startsWith('/api/location/nearby?') && k.includes(`kind=${kind}`) && k.includes('lat='));
	if (near) return json({ ...structuredClone(near[1].body), places: near[1].body.places.slice(0, lim) });
	return json({ places: [], location: S.location?.current ? { lat: S.location.current.lat, lon: S.location.current.lon } : null });
});
on('GET', /^\/api\/location\/search$/, (_, r) => {
	const exact = rec(r.url.pathname + r.url.search);
	if (exact) return replayRecord(exact);
	const q = (r.url.searchParams.get('q') || '').toLowerCase().trim();
	const seen = new Set<string>();
	const results: any[] = [];
	for (const [k, v] of Object.entries(R.get)) {
		if (!k.startsWith('/api/location/search?') && !k.startsWith('/api/location/nearby?')) continue;
		for (const p of v.body?.results || v.body?.places || []) {
			const id = `${p.name}|${p.lat}|${p.lon}`;
			if (q && p.name?.toLowerCase().includes(q) && !seen.has(id)) {
				seen.add(id);
				results.push(p);
			}
		}
	}
	const shape = Object.entries(R.get).find(([k]) => k.startsWith('/api/location/search?'))?.[1]?.body;
	return json({ ...(shape && typeof shape === 'object' ? structuredClone(shape) : {}), results: results.slice(0, 12) });
});
on('POST', /^\/api\/route$/, async (_, r) => {
	const to = r.body?.to;
	const rt = R.route;
	if (!rt || rt.status !== 200) return fail(503, "Offline directions aren't part of this demo.");
	if (!S.location?.current) return fail(400, 'Set your location first (tap the map), or connect a GPS.');
	const d = to ? Math.hypot((to.lat - rt.to.lat) * 111, (to.lon - rt.to.lon) * 111 * Math.cos((to.lat * Math.PI) / 180)) : 1e9;
	if (d > 6) return fail(422, `This demo has one recorded route: from Old Faithful to ${rt.to.name}. Search for ${rt.to.name} to see it.`);
	await wait((rt.body?.ms || 300) / demo.speed() + 120);
	return json(structuredClone(rt.body));
});

// people
on('GET', /^\/api\/users$/, () => json(S.users));
on('POST', /^\/api\/users$/, (_, r) => {
	const name = String(r.body?.name || '').trim();
	if (!name) return fail(400, 'Name is required');
	const u = { id: newId('u_'), name, role: r.body?.role || 'user', color: '#8AB4FF', has_pin: !!r.body?.pin, has_password: !!r.body?.password, created_at: now() };
	S.users.push(u);
	save();
	return json(u);
});
on('PATCH', /^\/api\/users\/([^/]+)$/, ([, id], r) => {
	const u = S.users.find((x) => x.id === id) || (boot().me?.id === id ? { ...boot().me } : null);
	if (!u) return fail(404, 'Not Found');
	if ('pin' in (r.body || {})) u.has_pin = !!r.body.pin;
	if ('password' in (r.body || {})) u.has_password = !!r.body.password;
	if (r.body?.name) u.name = r.body.name;
	save();
	return json(u);
});
on('DELETE', /^\/api\/users\/([^/]+)$/, ([, id]) => {
	const i = S.users.findIndex((x) => x.id === id && x.role !== 'owner');
	if (i >= 0) S.users.splice(i, 1);
	save();
	return json({ ok: i >= 0 });
});

// sign-in: the demo has one account, already signed in
on('POST', /^\/api\/auth\/logout$/, () => {
	try {
		sessionStorage.setItem('mimi.demo.signout', '1');
	} catch {}
	return json({ ok: true });
});
on('POST', /^\/api\/auth\/(login|guest|unlock|setup)$/, () => json({ ok: true, me: boot().me }));
on('GET', /^\/api\/auth\/pair\/pending$/, () => json({ requests: [] }));
on('POST', /^\/api\/auth\/pair/, () => NOT_HERE('Signing in other devices'));

// things that need the device
on('POST', /^\/api\/uploads$/, () => NOT_HERE('Attaching files'));
on('POST', /^\/api\/files$/, () => NOT_HERE('Adding your own files'));
on('DELETE', /^\/api\/files\/[^/]+$/, () => json({ ok: true }));
on('GET', /^\/api\/files\/search$/, () => json({ results: [] }));
on('POST', /^\/api\/voice\/(stt|tts)$/, ([, k]) => NOT_HERE(k === 'stt' ? 'Speech recognition' : 'Reading answers aloud'));
on('POST', /^\/api\/voice\/warm$/, () => json({ ok: true }));
on('POST', /^\/api\/lens\/ocr$/, () => NOT_HERE('Reading photos'));
on('POST', /^\/api\/scribe$/, () => NOT_HERE('Recording notes'));
on('GET', /^\/api\/scribe\/[^/]+$/, () => fail(404, 'Not Found'));
on('POST', /^\/api\/models\/(load|unload)$/, () => fail(503, "Models don't run in the browser demo: the answers here were recorded from a real Mimi."));
on('POST', /^\/api\/tools\/reload$/, () => json(body('/api/tools')));
on('POST', /^\/api\/(system|share)\//, () => fail(503, "That changes the device itself, so it isn't part of the browser demo."));

/** Answer one request the app made to Core. */
export async function handle(r: Req): Promise<Response> {
	const path = r.url.pathname;
	for (const [method, re, h] of routes) {
		if (method !== r.method) continue;
		const m = path.match(re);
		if (m) return h(m, r);
	}
	if (r.method === 'GET' || r.method === 'HEAD') {
		const hit = rec(path + r.url.search) ?? rec(path);
		if (hit) return replayRecord(hit);
		return fail(404, "That isn't part of the browser demo.");
	}
	return fail(503, "That isn't part of the browser demo.");
}
