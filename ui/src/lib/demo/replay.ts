// Replays a recorded chat turn as the Server-Sent Events stream Core would send, paced by
// the recorded timings: sources first, the "From the source" excerpt while Mimi reads, then
// the answer at the reference handheld's speed (about 8 tokens/s). "Skip the wait" speeds
// the clock up, mid-answer too.
import { chatById, json, newChat, newId, R, save, touchChat } from './core';
import { demo } from './state.svelte';

export type Turn = { id: string; question: string; title: string; match: string[][]; events: [number, string, any][]; thread: any };

export const HONEST = (questions: string[]) =>
	"This demo plays recorded answers, so I can't look that up here. Try one of these:\n\n" +
	questions.map((q) => `- ${q}`).join('\n') +
	"\n\nOn a real Mimi, I'd search the offline library on your device and answer with sources.";

const norm = (s: string) =>
	s
		.toLowerCase()
		.normalize('NFKD')
		.replace(/[̀-ͯ]/g, '')
		.replace(/[^a-z0-9\s]/g, ' ')
		.replace(/\s+/g, ' ')
		.trim();

/** The recorded turn a visitor's question stands for, if any (a few synonyms, word stems). */
export function pickTurn(text: string): Turn | null {
	const t = norm(text);
	const words = t.split(' ');
	const exact = R.chats.find((c) => norm(c.question) === t);
	if (exact) return exact;
	const has = (k: string) => (k.includes(' ') ? t.includes(k) : words.some((w) => w.startsWith(k)));
	for (const c of [...R.chats].sort((a, b) => b.match.length - a.match.length)) {
		if (c.id === 'chitchat') {
			if (words.length <= 4 && c.match.every((g) => g.some((k) => words.includes(k)))) return c;
		} else if (c.match.every((g) => g.some(has))) return c;
	}
	return null;
}

/** A turn for a question the demo has no recording of: an honest reply, paced like small talk. */
function honestTurn(): Turn {
	const base = R.chats.find((c) => c.id === 'chitchat') ?? R.chats[0];
	const text = HONEST(R.chats.map((c) => c.question));
	const deltas = base.events.filter(([, e]) => e === 'delta');
	const first = deltas[0]?.[0] ?? 1200;
	const gap = deltas.length > 1 ? (deltas[deltas.length - 1][0] - first) / (deltas.length - 1) : 120;
	const words = text.split(' ');
	const events: Turn['events'] = base.events.filter(([, e]) => e === 'meta' || e === 'status').map((e) => structuredClone(e));
	words.forEach((w, i) => events.push([Math.round(first + i * gap), 'delta', { text: w + (i < words.length - 1 ? ' ' : '') }]));
	const done = structuredClone(base.events.find(([, e]) => e === 'done')!);
	done[0] = Math.round(first + words.length * gap);
	done[2].message.content = text;
	if (done[2].message.meta?.timings) done[2].message.meta.timings.predicted_n = words.length;
	events.push(done);
	const thread = structuredClone(base.thread);
	thread.messages[thread.messages.length - 1].content = text;
	return { ...base, id: 'honest', title: '', events, thread };
}

/** Fill a recorded turn's placeholders with this replay's ids and the visitor's words. */
function fill<T>(x: T, ids: Record<string, string>): T {
	let s = JSON.stringify(x);
	for (const [k, v] of Object.entries(ids)) s = s.split(`{{${k}}}`).join(v);
	return JSON.parse(s);
}

const live = new Map<string, () => boolean>();

/** Stop the turn playing in this chat (Core's /stop). */
export function stopReplay(chatId: string): boolean {
	return live.get(chatId)?.() ?? false;
}

export function replay(chatId: string, body: { content?: string; mode?: string; regenerate?: string; edit?: string }, signal?: AbortSignal): Response {
	const chat = chatId === 'new' ? newChat('', body.mode || 'everyday') : chatById(chatId);
	if (!chat) return json({ detail: 'Chat not found' }, 404);
	const t = Date.now() / 1000;

	// Where the new messages go: a regenerated answer replaces the old one; an edit replaces its question.
	let question = String(body.content ?? '');
	let userMsg: any = null;
	if (body.regenerate) {
		const i = chat.messages.findIndex((m) => m.id === body.regenerate);
		if (i >= 0) {
			const keep = chat.messages[i].role === 'user' ? i + 1 : i;
			chat.messages = chat.messages.slice(0, keep);
			userMsg = chat.messages[keep - 1] ?? null;
			question = userMsg?.content ?? question;
		}
	} else if (body.edit) {
		const i = chat.messages.findIndex((m) => m.id === body.edit);
		if (i >= 0) chat.messages = chat.messages.slice(0, i);
	}
	const turn = pickTurn(question) ?? honestTurn();
	const ids = { chat: chat.id, user: userMsg?.id ?? newId('msg_'), assistant: newId('msg_') };
	const events = fill(turn.events, ids);
	const thread = fill(turn.thread, ids);
	const parentId = chat.messages[chat.messages.length - 1]?.id ?? null;
	const versions = (id: string) => ({ ids: [id], index: 0, count: 1 });
	if (!userMsg) {
		userMsg = { ...thread.messages[0], content: question, parent_id: parentId, created_at: t, versions: versions(ids.user) };
		userMsg.meta = { ...(userMsg.meta || {}), context: undefined };
		chat.messages.push(userMsg);
	}
	const assistant = { ...thread.messages[thread.messages.length - 1], parent_id: userMsg.id, versions: versions(ids.assistant) };
	if (!chat.title) chat.title = turn.title || question.slice(0, 60);
	touchChat(chat);

	// What the stream says about the question and chat follows this conversation, not the recording.
	for (const [, ev, d] of events) {
		if (ev === 'meta') {
			d.user_message = userMsg;
			d.title = chat.title;
		}
		if (ev === 'done') {
			if (d.chat) d.chat.title = chat.title;
			d.message.parent_id = userMsg.id;
			d.message.created_at = t;
		}
	}

	const enc = new TextEncoder();
	let i = 0;
	let virtual = 0;
	let last = performance.now();
	let timer: ReturnType<typeof setTimeout> | undefined;
	let said = '';
	let stopped = false;
	let ended = false;
	let ctrl!: ReadableStreamDefaultController<Uint8Array>;

	const send = (ev: string, data: unknown) => ctrl.enqueue(enc.encode(`event: ${ev}\ndata: ${JSON.stringify(data)}\n\n`));
	const finish = (final: any) => {
		if (ended) return;
		ended = true;
		clearTimeout(timer);
		live.delete(chat.id);
		demo.playing = false;
		chat.messages.push({ ...assistant, ...final, created_at: Date.now() / 1000 });
		chat.head_id = final.id;
		touchChat(chat);
		save();
		try {
			ctrl.close();
		} catch {
			/* already closed */
		}
		if (!stopped) window.dispatchEvent(new CustomEvent('mimi-demo:answered', { detail: { turn: turn.id } }));
	};
	const tick = () => {
		const n = performance.now();
		virtual += (n - last) * demo.speed();
		last = n;
		if (stopped) {
			const done = events.find(([, e]) => e === 'done')?.[2];
			const msg = { ...(done?.message ?? assistant), content: said, meta: { ...(done?.message?.meta ?? assistant.meta), cancelled: true, grounding: undefined } };
			send('done', { message: msg, chat: { id: chat.id, title: chat.title } });
			return finish(msg);
		}
		while (i < events.length && events[i][0] <= virtual) {
			const [, ev, data] = events[i++];
			if (ev === 'delta') said += data.text;
			send(ev, data);
			if (ev === 'done') return finish({ ...data.message, meta: { ...data.message.meta } });
		}
		if (i >= events.length) return finish({ ...assistant, content: said });
		timer = setTimeout(tick, Math.min(100, Math.max(4, (events[i][0] - virtual) / demo.speed())));
	};
	const stream = new ReadableStream<Uint8Array>({
		start(c) {
			ctrl = c;
			demo.playing = true;
			live.set(chat.id, () => {
				if (ended) return false;
				stopped = true;
				clearTimeout(timer);
				tick();
				return true;
			});
			tick();
		},
		cancel() {
			stopped = true;
			clearTimeout(timer);
			if (!ended) finish({ ...assistant, content: said, meta: { ...assistant.meta, cancelled: true } });
		}
	});
	signal?.addEventListener('abort', () => {
		clearTimeout(timer);
		if (!ended) {
			ended = true;
			live.delete(chat.id);
			demo.playing = false;
			try {
				ctrl.error(new DOMException('The user aborted a request.', 'AbortError'));
			} catch {
				/* closed */
			}
		}
	});
	return new Response(stream, { headers: { 'content-type': 'text/event-stream' } });
}
