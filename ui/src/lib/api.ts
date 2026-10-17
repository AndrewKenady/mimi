// Thin client for Mimi Core's HTTP API.
import { fmtDate, fmtNumber, i18n, t } from './i18n/index.svelte';

export class ApiError extends Error {
	status: number;
	constructor(status: number, message: string) {
		super(message);
		this.status = status;
	}
}

type Opts = { method?: string; body?: unknown; form?: FormData; signal?: AbortSignal; raw?: boolean };

export async function api<T = any>(path: string, opts: Opts = {}): Promise<T> {
	// Core words its own messages (status lines, errors) in the language the interface shows.
	const headers: Record<string, string> = { 'x-mimi-locale': i18n.locale };
	const init: RequestInit = { method: opts.method ?? (opts.body || opts.form ? 'POST' : 'GET'), credentials: 'same-origin', signal: opts.signal, headers };
	if (opts.form) init.body = opts.form;
	else if (opts.body !== undefined) {
		init.body = JSON.stringify(opts.body);
		headers['content-type'] = 'application/json';
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
		throw new ApiError(res.status, msg || t('shell.requestFailed', { status: res.status }));
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
		headers: { 'content-type': 'application/json', accept: 'text/event-stream', 'x-mimi-locale': i18n.locale },
		body: JSON.stringify(body),
		signal
	});
	if (!res.ok || !res.body) {
		let msg = t('shell.requestFailed', { status: res.status });
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

/** A size in the interface language: "1.5 GB", "1,5 GB", "1,5 Go". */
export function fmtBytes(n: number): string {
	const u = t('shell.byteUnits').split(' ');
	if (!n) return `${fmtNumber(0)} ${u[0]}`;
	const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
	const digits = i >= 3 ? 1 : 0;
	return `${fmtNumber(n / 1024 ** i, { minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: false })} ${u[i]}`;
}

/** How long ago a Unix time was, briefly ("5m ago"), or its date once it is a week old. */
export function timeAgo(ts: number): string {
	const s = Date.now() / 1000 - ts;
	if (s < 45) return t('shell.justNow');
	if (s < 3600) return t('shell.minutesAgo', { n: fmtNumber(Math.round(s / 60)) });
	if (s < 86400) return t('shell.hoursAgo', { n: fmtNumber(Math.round(s / 3600)) });
	if (s < 86400 * 7) return t('shell.daysAgo', { n: fmtNumber(Math.round(s / 86400)) });
	return fmtDate(ts * 1000, { month: 'short', day: 'numeric' });
}
