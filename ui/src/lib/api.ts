// Thin client for MIMI Core's HTTP API.

export class ApiError extends Error {
	status: number;
	constructor(status: number, message: string) {
		super(message);
		this.status = status;
	}
}

type Opts = { method?: string; body?: unknown; form?: FormData; signal?: AbortSignal; raw?: boolean };

export async function api<T = any>(path: string, opts: Opts = {}): Promise<T> {
	const init: RequestInit = { method: opts.method ?? (opts.body || opts.form ? 'POST' : 'GET'), credentials: 'same-origin', signal: opts.signal };
	if (opts.form) init.body = opts.form;
	else if (opts.body !== undefined) {
		init.body = JSON.stringify(opts.body);
		init.headers = { 'content-type': 'application/json' };
	}
	const res = await fetch(path.startsWith('/') ? path : `/api/${path}`, init);
	if (!res.ok) {
		let msg = res.statusText;
		try {
			const j = await res.json();
			msg = typeof j.detail === 'string' ? j.detail : j.detail?.[0]?.msg ?? msg;
		} catch {
			/* not JSON */
		}
		throw new ApiError(res.status, msg || `Request failed (${res.status})`);
	}
	if (opts.raw) return res as unknown as T;
	const ct = res.headers.get('content-type') || '';
	return (ct.includes('json') ? res.json() : res.text()) as Promise<T>;
}

export const get = <T = any>(p: string) => api<T>(p);
export const post = <T = any>(p: string, body?: unknown) => api<T>(p, { method: 'POST', body: body ?? {} });
export const patch = <T = any>(p: string, body: unknown) => api<T>(p, { method: 'PATCH', body });
export const del = <T = any>(p: string) => api<T>(p, { method: 'DELETE' });

export async function upload<T = any>(path: string, file: Blob, name = 'file', extra: Record<string, string> = {}): Promise<T> {
	const fd = new FormData();
	fd.append('file', file, (file as File).name || name);
	for (const [k, v] of Object.entries(extra)) fd.append(k, v);
	return api<T>(path, { form: fd });
}

export type SSEEvent = { event: string; data: any };

/** POST a JSON body and iterate Server-Sent Events from the response. */
export async function* stream(path: string, body: unknown, signal?: AbortSignal): AsyncGenerator<SSEEvent> {
	const res = await fetch(path, {
		method: 'POST',
		credentials: 'same-origin',
		headers: { 'content-type': 'application/json', accept: 'text/event-stream' },
		body: JSON.stringify(body),
		signal
	});
	if (!res.ok || !res.body) {
		let msg = `Request failed (${res.status})`;
		try {
			msg = (await res.json()).detail ?? msg;
		} catch {
			/* ignore */
		}
		throw new ApiError(res.status, msg);
	}
	const reader = res.body.getReader();
	const dec = new TextDecoder();
	let buf = '';
	for (;;) {
		const { value, done } = await reader.read();
		if (done) break;
		buf += dec.decode(value, { stream: true });
		let idx: number;
		while ((idx = buf.indexOf('\n\n')) >= 0) {
			const block = buf.slice(0, idx);
			buf = buf.slice(idx + 2);
			let ev = 'message';
			const data: string[] = [];
			for (const line of block.split('\n')) {
				if (line.startsWith('event:')) ev = line.slice(6).trim();
				else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
			}
			if (!data.length) continue;
			try {
				yield { event: ev, data: JSON.parse(data.join('\n')) };
			} catch {
				/* malformed chunk */
			}
		}
	}
}

export function fmtBytes(n: number): string {
	if (!n) return '0 B';
	const u = ['B', 'KB', 'MB', 'GB', 'TB'];
	const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
	return `${(n / 1024 ** i).toFixed(i >= 3 ? 1 : 0)} ${u[i]}`;
}

export function timeAgo(ts: number): string {
	const s = Date.now() / 1000 - ts;
	if (s < 45) return 'just now';
	if (s < 3600) return `${Math.round(s / 60)}m ago`;
	if (s < 86400) return `${Math.round(s / 3600)}h ago`;
	if (s < 86400 * 7) return `${Math.round(s / 86400)}d ago`;
	return new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
