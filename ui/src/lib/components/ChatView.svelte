<script lang="ts">
	import { goto } from '$app/navigation';
	import { onDestroy, onMount, tick } from 'svelte';
	import { app } from '$lib/app.svelte';
	import { del, get, patch, post, stream, timeAgo } from '$lib/api';
	import { Speaker } from '$lib/audio';
	import { t } from '$lib/i18n/index.svelte';
	import Composer from './Composer.svelte';
	import Message from './Message.svelte';
	import Well from './Well.svelte';
	import type { Progress } from './TurnProgress.svelte';
	import { SquarePen, Search, Pin, PinOff, Trash2, PanelLeftClose, PanelLeft, Download, Archive, EllipsisVertical, MessagesSquare, Pencil, Folder, FolderInput, ArchiveRestore, Check, ArrowDown } from '@lucide/svelte';

	let { id = null }: { id?: string | null } = $props();

	let chat = $state<any>(null);
	let messages = $state<any[]>([]);
	let list = $state<any[]>([]);
	let q = $state('');
	let busy = $state(false);
	/** The live turn's narrative, from the stream's `status` events. */
	let progress = $state<Progress | null>(null);
	/** Polite screen-reader announcements: status changes, never individual tokens. */
	let announce = $state('');
	let mode = $state(app.settings.user?.assistant?.default_mode || 'everyday');
	let draft = $state('');
	let attachments = $state<any[]>([]);
	let scroller: HTMLDivElement | undefined = $state();
	// Follow the stream only while the reader is at the bottom; scrolling up opts out.
	let stick = $state(true);
	let unseen = $state(false);
	let lastTop = 0;
	let abort: AbortController | null = null;
	let stopWanted = false;
	let narrow = $state(false); // the chat list overlays the thread instead of sitting beside it
	const reduceMotion = () =>
		matchMedia('(prefers-reduced-motion: reduce)').matches || document.documentElement.dataset.motion === 'reduced';
	// The chat list remembers whether it was open (phones always start with it closed).
	let sideOpen = $state(readSide());
	function readSide() {
		if (typeof innerWidth !== 'undefined' && innerWidth < 900) return false;
		try {
			const v = localStorage.getItem('mimi.chatSide');
			if (v) return v === '1';
		} catch {}
		return typeof innerWidth === 'undefined' || innerWidth > 1100;
	}
	$effect(() => {
		const open = sideOpen;
		try {
			if (innerWidth >= 900) localStorage.setItem('mimi.chatSide', open ? '1' : '0');
		} catch {}
	});
	let menuFor = $state<string | null>(null);
	let renaming = $state<string | null>(null);
	let renameText = $state('');
	let loadedId: string | null = null;
	// Folders ("projects") and the archive. '' = all chats, ARCHIVE = archived ones.
	const ARCHIVE = ':archived';
	let projects = $state<string[]>([]);
	let folder = $state('');
	let moving = $state<string | null>(null);
	let newFolder = $state('');

	async function loadList() {
		try {
			const qs = new URLSearchParams();
			if (q.trim()) qs.set('q', q.trim());
			if (folder === ARCHIVE) qs.set('archived', 'true');
			else if (folder) qs.set('project', folder);
			const r = await get(`/api/chats${qs.size ? '?' + qs : ''}`);
			list = r.chats;
			projects = r.projects || [];
			if (folder && folder !== ARCHIVE && !projects.includes(folder)) {
				folder = '';
				loadList();
			}
		} catch {
			/* offline */
		}
	}
	function pickFolder(f: string) {
		folder = folder === f ? '' : f;
		loadList();
	}
	async function moveTo(c: any, name: string) {
		await patch(`/api/chats/${c.id}`, { project: name.trim() });
		moving = null;
		menuFor = null;
		newFolder = '';
		app.toast(name.trim() ? t('chat.movedTo', { name: name.trim() }) : t('chat.removedFromFolder'));
		loadList();
	}
	async function unarchive(c: any) {
		await patch(`/api/chats/${c.id}`, { archived: false });
		menuFor = null;
		loadList();
	}

	async function loadChat(cid: string | null) {
		if (cid === loadedId && chat) return;
		loadedId = cid;
		if (!cid) {
			chat = null;
			messages = [];
			return;
		}
		try {
			const c = await get(`/api/chats/${cid}`);
			chat = c;
			messages = c.messages;
			if (c.mode) mode = c.mode;
			stick = true;
			await tick();
			scrollBottom(true);
		} catch {
			app.toast(t('chat.chatGone'), 'error');
			goto('/chat', { replaceState: true });
		}
	}

	$effect(() => {
		const cid = id;
		if (!busy) loadChat(cid);
	});
	$effect(() => {
		app.chatsVersion;
		loadList();
	});

	onMount(() => {
		const p = app.pendingPrompt;
		if (p) {
			app.pendingPrompt = null;
			if (p.mode) mode = p.mode;
			if (p.send) send(p.text, p.attachments || []);
			else {
				draft = p.text;
				attachments = p.attachments || [];
			}
		}
		const mq = matchMedia('(max-width: 1100px)');
		const onMq = () => (narrow = mq.matches);
		onMq();
		mq.addEventListener('change', onMq);
		return () => mq.removeEventListener('change', onMq);
	});

	function onScroll() {
		if (!scroller) return;
		const top = scroller.scrollTop;
		const dist = scroller.scrollHeight - top - scroller.clientHeight;
		if (dist < 64) {
			stick = true;
			unseen = false;
		} else if (top < lastTop - 1) stick = false; // the reader moved up: stop following
		lastTop = top;
	}
	function scrollBottom(force = false) {
		if (!scroller) return;
		if (stick || force) {
			scroller.scrollTop = scroller.scrollHeight;
			lastTop = scroller.scrollTop;
		} else unseen = true;
	}
	function jumpToLatest() {
		stick = true;
		unseen = false;
		scroller?.scrollTo({ top: scroller.scrollHeight, behavior: reduceMotion() ? 'auto' : 'smooth' });
	}

	async function send(text: string, atts: any[], opts: { regenerate?: string; edit?: string } = {}) {
		if (busy) return;
		busy = true;
		stopWanted = false;
		const started = Date.now();
		progress = { state: 'thinking', label: t('chat.thinking'), at: started, started, stages: [] };
		announce = '';
		stick = true;
		unseen = false;
		const readAloud = app.settings.user?.voice?.read_aloud;
		reader?.close(); // one read-aloud at a time: a new answer replaces the previous one
		const speaker = readAloud ? (reader = new Speaker(app.settings.user?.voice?.voice, app.settings.user?.voice?.speed)) : null;
		const live: any = { id: 'live', role: 'assistant', content: '', meta: { tools: [], sources: [], memory_suggested: [] } };
		// Placeholders from a failed attempt make way for the new one.
		messages = messages.filter((x) => x.id !== 'failed' && x.id !== 'pending');
		if (opts.regenerate) {
			const idx = messages.findIndex((x) => x.id === opts.regenerate);
			// an assistant id is replaced by a new version; a user id (a retry) keeps its question
			const keep = idx < 0 ? messages.length : messages[idx].role === 'user' ? idx + 1 : idx;
			messages = [...messages.slice(0, keep), live];
		} else if (opts.edit) {
			const idx = messages.findIndex((x) => x.id === opts.edit);
			messages = [...messages.slice(0, idx), { id: 'pending', role: 'user', content: text, meta: { attachments: atts } }, live];
		} else {
			messages = [...messages, { id: 'pending', role: 'user', content: text, meta: { attachments: atts } }, live];
		}
		await tick();
		scrollBottom(true);
		abort = new AbortController();
		const liveIdx = () => messages.findIndex((x) => x.id === 'live');
		const update = (fn: (m: any) => void) => {
			const i = liveIdx();
			if (i < 0) return;
			const m = { ...messages[i], meta: { ...messages[i].meta } };
			fn(m);
			messages[i] = m;
		};
		// Tokens arrive faster than it is useful to paint them: batch them per animation frame.
		let pendingText = '';
		let raf = 0;
		const flushText = () => {
			if (raf) cancelAnimationFrame(raf);
			raf = 0;
			if (!pendingText) return;
			const text = pendingText;
			pendingText = '';
			update((m) => (m.content += text));
			tick().then(() => scrollBottom());
		};
		let gotMeta = false;
		let gotDone = false;
		let userId: string | null = null;
		try {
			const body = { content: text, attachments: atts.map((a) => a.id), mode, regenerate: opts.regenerate, edit: opts.edit };
			for await (const ev of stream(`/api/chats/${chat?.id || 'new'}/messages`, body, abort.signal)) {
				const d = ev.data;
				if (ev.event === 'delta') {
					pendingText += d.text;
					speaker?.feed(d.text);
					if (!raf) raf = requestAnimationFrame(flushText);
					continue;
				}
				flushText();
				if (ev.event === 'meta') {
					gotMeta = true;
					userId = d.user_message?.id ?? null;
					if (!chat) {
						chat = { id: d.chat_id, title: d.title };
						loadedId = d.chat_id;
						goto(`/chat/${d.chat_id}`, { replaceState: true, noScroll: true, keepFocus: true });
					}
					const pi = messages.findIndex((x) => x.id === 'pending');
					if (pi >= 0 && d.user_message) messages[pi] = d.user_message;
					if (stopWanted) stop(); // Stop was pressed before the chat existed
				} else if (ev.event === 'status') {
					const prev: Progress | null = progress;
					progress = {
						state: d.state,
						label: d.label,
						eta_ms: d.eta_ms,
						at: Date.now(),
						started,
						stages: [...(prev?.stages || []).filter((s) => s !== d.state), d.state]
					};
					if (d.label && d.label !== prev?.label) announce = d.label;
				} else if (ev.event === 'preview') update((m) => (m.meta.preview = d));
				else if (ev.event === 'tool') {
					update((m) => {
						const tools = [...m.meta.tools];
						const k = tools.findIndex((x: any) => x.id === d.id);
						if (k >= 0) tools[k] = { ...tools[k], ...d };
						else tools.push(d);
						m.meta.tools = tools;
					});
				} else if (ev.event === 'sources') update((m) => (m.meta.sources = d.sources));
				else if (ev.event === 'grounding') update((m) => (m.meta.grounding = { ...(m.meta.grounding || {}), flags: d.flags }));
				else if (ev.event === 'memory') {
					update((m) => {
						if (d.used) m.meta.memories_used = d.used;
						if (d.suggested) m.meta.memory_suggested = [...(m.meta.memory_suggested || []), ...d.suggested];
						if (d.saved) app.toast(t('chat.remembered', { text: `${d.saved[0]?.text}` }), 'ok');
					});
				} else if (ev.event === 'error') {
					update((m) => (m.meta.error = d.message));
				} else if (ev.event === 'done') {
					gotDone = true;
					const i = liveIdx();
					const sugg = i >= 0 ? messages[i].meta.memory_suggested : [];
					const final = { ...d.message, meta: { ...d.message.meta, memory_suggested: sugg } };
					if (i >= 0) messages[i] = final;
					if (d.chat?.title) chat = { ...chat, title: d.chat.title };
					speaker?.flush();
					if (final.meta?.error) announce = t('chat.couldntFinish', { error: final.meta.error });
				}
				await tick();
				scrollBottom();
			}
		} catch (e: any) {
			if (e.name !== 'AbortError') update((m) => (m.meta.error = e.message || t('chat.connectionLost')));
		} finally {
			flushText();
			// A turn that ended without an answer (no model, connection lost…) leaves a retryable error.
			const liveMsg = messages.find((x) => x.id === 'live');
			const failure = !gotDone ? liveMsg?.meta?.error || (stopWanted ? '' : t('chat.stoppedBeforeAnswering')) : '';
			if (failure) announce = t('chat.couldntAnswer', { error: failure });
			const failed = (retry_of: string | null) => ({
				...(liveMsg || {}),
				id: 'failed',
				role: 'assistant',
				meta: { ...(liveMsg?.meta || {}), error: failure, retry_of, retry_text: text, retry_atts: atts }
			});
			busy = false;
			progress = null;
			abort = null;
			loadList();
			// Pull the canonical thread (versions, ids) once streaming is done.
			const c = chat?.id && gotMeta ? await get(`/api/chats/${chat.id}`).catch(() => null) : null;
			if (c) {
				const sugg = messages.find((x) => x.meta?.memory_suggested?.length)?.meta.memory_suggested;
				messages = c.messages.map((x: any, i: number) => (i === c.messages.length - 1 && sugg ? { ...x, meta: { ...x.meta, memory_suggested: sugg } } : x));
				chat = { ...chat, ...c };
				const last = c.messages[c.messages.length - 1];
				if (failure && last?.role === 'user') messages = [...messages, failed(last.id)];
			} else if (liveMsg) {
				// Nothing was stored server-side: keep the question on screen with a way to resend it.
				messages = messages.map((x) => (x.id === 'live' ? failed(userId) : x));
				if (!failure) messages = messages.filter((x) => x.id !== 'failed');
			}
		}
	}

	async function stop() {
		reader?.stop(); // Stop also silences an answer that is still being read aloud
		if (!busy) return;
		stopWanted = true;
		if (!chat?.id) return; // sent as soon as the stream says which chat this is
		const r = await post(`/api/chats/${chat.id}/stop`).catch(() => null);
		// The turn registers itself a moment after it starts; one late retry covers that gap.
		if (r && !r.stopped) setTimeout(() => busy && post(`/api/chats/${chat.id}/stop`).catch(() => {}), 400);
	}

	function retryFor(m: any): (() => void) | undefined {
		if (busy || m.role !== 'assistant' || m.id === 'live') return undefined;
		if (m.id === 'failed') {
			const { retry_of, retry_text, retry_atts } = m.meta || {};
			return retry_of ? () => send('', [], { regenerate: retry_of }) : () => send(retry_text || '', retry_atts || []);
		}
		return m === lastAssistant ? () => send('', [], { regenerate: m.id }) : undefined;
	}
	let reader: Speaker | null = null;
	onDestroy(() => reader?.close());

	async function switchVersion(mid: string) {
		const c = await post(`/api/chats/${chat.id}/head`, { message_id: mid });
		messages = c.messages;
	}

	function newChat() {
		chat = null;
		messages = [];
		loadedId = null;
		closeOverlay();
		goto('/chat');
	}

	/** On narrow screens the chat list is an overlay: it closes once a chat is picked. */
	function closeOverlay() {
		if (narrow) sideOpen = false;
	}
	function onWindowKey(e: KeyboardEvent) {
		if (e.key !== 'Escape' || e.defaultPrevented || app.palette || app.quick || app.voice) return;
		if (menuFor) menuFor = null;
		else if (narrow && sideOpen) sideOpen = false;
	}

	async function togglePin(c: any) {
		await patch(`/api/chats/${c.id}`, { pinned: !c.pinned });
		menuFor = null;
		loadList();
	}
	async function archive(c: any) {
		await patch(`/api/chats/${c.id}`, { archived: true });
		menuFor = null;
		if (c.id === chat?.id) newChat();
		loadList();
	}
	// Deleting is deferred for a few seconds so the toast's Undo can take it back.
	const UNDO_MS = 6000;
	const pendingDeletes = new Map<string, ReturnType<typeof setTimeout>>();
	let hidden = $state<string[]>([]);
	const shown = $derived(list.filter((c) => !hidden.includes(c.id)));
	function remove(c: any) {
		menuFor = null;
		const wasOpen = c.id === chat?.id;
		hidden = [...hidden, c.id];
		if (wasOpen) newChat();
		pendingDeletes.set(c.id, setTimeout(() => commitDelete(c.id), UNDO_MS + 400));
		// Closing the tab must not cancel a delete the user meant; only Undo does.
		addEventListener('pagehide', () => flushDeletes(true), { once: true });
		app.toast(t('chat.deleted', { title: c.title || t('chat.newChat') }), 'info', { label: t('chat.undo'), run: () => undoDelete(c.id, wasOpen) }, UNDO_MS);
	}
	async function commitDelete(cid: string, unloading = false) {
		clearTimeout(pendingDeletes.get(cid));
		pendingDeletes.delete(cid);
		if (unloading) {
			fetch(`/api/chats/${cid}`, { method: 'DELETE', credentials: 'same-origin', keepalive: true }).catch(() => {});
			return;
		}
		try {
			await del(`/api/chats/${cid}`);
		} catch {
			app.toast(t('chat.deleteFailed'), 'error');
		}
		hidden = hidden.filter((x) => x !== cid);
		loadList();
	}
	function undoDelete(cid: string, reopen: boolean) {
		if (!pendingDeletes.has(cid)) return;
		clearTimeout(pendingDeletes.get(cid));
		pendingDeletes.delete(cid);
		hidden = hidden.filter((x) => x !== cid);
		if (reopen) goto(`/chat/${cid}`);
	}
	function flushDeletes(unloading = false) {
		for (const cid of [...pendingDeletes.keys()]) commitDelete(cid, unloading);
	}
	// (Pending deletes outlive this view on purpose: Undo still works after navigating away.)
	async function saveRename(c: any) {
		if (renameText.trim()) await patch(`/api/chats/${c.id}`, { title: renameText.trim() });
		renaming = null;
		loadList();
		if (c.id === chat?.id) chat = { ...chat, title: renameText.trim() };
	}

	const lastAssistant = $derived([...messages].reverse().find((x) => x.role === 'assistant'));
	const hour = new Date().getHours();
	const greeting = $derived(t(hour < 5 ? 'chat.greetLate' : hour < 12 ? 'chat.greetMorning' : hour < 18 ? 'chat.greetAfternoon' : 'chat.greetEvening'));
	const suggestions = $derived([t('chat.suggestion1'), t('chat.suggestion2'), t('chat.suggestion3'), t('chat.suggestion4')]);
</script>

<svelte:window onkeydown={onWindowKey} />

<div class="chat" class:side={sideOpen} class:narrow>
	{#if sideOpen && narrow}
		<div class="scrim" onclick={() => (sideOpen = false)} aria-hidden="true"></div>
	{/if}
	<aside class="list" aria-label={t('chat.chats')} inert={!sideOpen}>
		<div class="lhead">
			<button class="btn btn-primary new" onclick={newChat}><SquarePen size={16} /> {t('chat.newChat')}</button>
			<button class="icon-btn" onclick={() => (sideOpen = false)} aria-label={t('chat.hideList')}><PanelLeftClose size={18} /></button>
		</div>
		<div class="lsearch">
			<Search size={15} />
			<input placeholder={t('chat.searchChats')} bind:value={q} oninput={() => loadList()} />
		</div>
		<div class="folders" role="tablist" aria-label={t('chat.folders')}>
			<button role="tab" aria-selected={folder === ''} class:on={folder === ''} onclick={() => pickFolder('')}>{t('chat.allChats')}</button>
			{#each projects as p (p)}
				<button role="tab" aria-selected={folder === p} class:on={folder === p} onclick={() => pickFolder(p)}><Folder size={12} /> {p}</button>
			{/each}
			<button role="tab" aria-selected={folder === ARCHIVE} class:on={folder === ARCHIVE} onclick={() => pickFolder(ARCHIVE)}><Archive size={12} /> {t('chat.archived')}</button>
		</div>
		<div class="items" data-scroll>
			{#each shown as c (c.id)}
				<div class="it" class:on={c.id === chat?.id}>
					{#if renaming === c.id}
						<input class="input rn" bind:value={renameText} aria-label={t('chat.chatTitle')} onkeydown={(e) => { if (e.key === 'Enter') saveRename(c); if (e.key === 'Escape') { e.preventDefault(); renaming = null; } }} onblur={() => saveRename(c)} />
					{:else}
						<a href="/chat/{c.id}" class="il" aria-current={c.id === chat?.id ? 'page' : undefined} onclick={closeOverlay}>
							<span class="it-title">{#if c.pinned}<Pin size={12} class="pin" />{/if}<span class="tt">{c.title || t('chat.newChat')}</span></span>
							<span class="it-sub">{timeAgo(c.updated_at)}{c.preview ? ' · ' + c.preview : ''}</span>
						</a>
						<button class="icon-btn sm more" onclick={() => { menuFor = menuFor === c.id ? null : c.id; moving = null; }} aria-label={t('chat.optionsFor', { title: c.title || t('chat.newChat') })} aria-haspopup="menu" aria-expanded={menuFor === c.id}><EllipsisVertical size={15} /></button>
						{#if menuFor === c.id && moving === c.id}
							<div class="cmenu glass" role="menu">
								{#each projects as p (p)}
									<button onclick={() => moveTo(c, p)}><Folder size={14} /> {p}{#if c.project === p}<Check size={13} class="ck" />{/if}</button>
								{/each}
								{#if c.project}<button onclick={() => moveTo(c, '')}><FolderInput size={14} /> {t('chat.noFolder')}</button>{/if}
								<input class="input nf" placeholder={t('chat.newFolder')} bind:value={newFolder} onkeydown={(e) => { if (e.key === 'Enter' && newFolder.trim()) moveTo(c, newFolder); if (e.key === 'Escape') moving = null; }} />
							</div>
						{:else if menuFor === c.id}
							<div class="cmenu glass" role="menu">
								<button onclick={() => { renaming = c.id; renameText = c.title; menuFor = null; }}><Pencil size={14} /> {t('chat.rename')}</button>
								<button onclick={() => togglePin(c)}>{#if c.pinned}<PinOff size={14} /> {t('chat.unpin')}{:else}<Pin size={14} /> {t('chat.pin')}{/if}</button>
								<button onclick={() => (moving = c.id)}><FolderInput size={14} /> {t('chat.moveToFolder')}</button>
								<a href="/api/chats/{c.id}/export" download><Download size={14} /> {t('chat.export')}</a>
								{#if c.archived}
									<button onclick={() => unarchive(c)}><ArchiveRestore size={14} /> {t('chat.unarchive')}</button>
								{:else}
									<button onclick={() => archive(c)}><Archive size={14} /> {t('chat.archive')}</button>
								{/if}
								<button class="danger" onclick={() => remove(c)}><Trash2 size={14} /> {t('chat.delete')}</button>
							</div>
						{/if}
					{/if}
				</div>
			{:else}
				<div class="empty-list"><MessagesSquare size={20} /><span>{q ? t('chat.noMatches') : folder === ARCHIVE ? t('chat.noArchived') : folder ? t('chat.folderEmpty') : t('chat.listEmpty')}</span></div>
			{/each}
		</div>
	</aside>

	<section class="thread">
		<header class="thead">
			{#if !sideOpen}<button class="icon-btn" onclick={() => (sideOpen = true)} aria-label={t('chat.showList')}><PanelLeft size={18} /></button>{/if}
			<h1 class="ttl">{chat?.title || (messages.length ? t('chat.newChat') : '')}{#if !chat?.title && !messages.length}<span class="sr-only">{t('chat.newChat')}</span>{/if}</h1>
			{#if !sideOpen && messages.length}<button class="icon-btn" onclick={newChat} aria-label={t('chat.newChat')}><SquarePen size={18} /></button>{/if}
		</header>

		<div
			class="scroll"
			bind:this={scroller}
			onscroll={onScroll}
			data-scroll
			role="log"
			aria-label={t('chat.conversation')}
			aria-live="polite"
			aria-relevant="additions"
			aria-busy={busy}
		>
			<div class="inner">
				{#if !messages.length}
					<div class="hello fade-up">
						<Well size={150} mood="idle" />
						<h2>{app.me?.role !== 'guest' ? t('chat.greetingNamed', { greeting, name: `${app.me?.name}` }) : t('chat.greeting', { greeting })}</h2>
						<p>{t('chat.intro')}</p>
						<div class="sugg">
							{#each suggestions as s}<button class="chip" onclick={() => send(s, [])}>{s}</button>{/each}
						</div>
					</div>
				{/if}
				{#each messages as m (m.id)}
					<Message
						{m}
						live={m.id === 'live'}
						progress={m.id === 'live' ? progress : null}
						onregenerate={retryFor(m)}
						onswitch={!busy ? switchVersion : undefined}
						onedit={m.role === 'user' && !busy && m.id !== 'pending' ? (text) => send(text, [], { edit: m.id }) : undefined}
					/>
				{/each}
			</div>
		</div>
		<div class="sr-only" role="status" aria-live="polite" aria-atomic="true">{announce}</div>

		<div class="compose">
			{#if !stick && (busy || unseen)}
				<button class="jump glass" onclick={jumpToLatest}>
					<ArrowDown size={15} />{t('chat.jumpToLatest')}
				</button>
			{/if}
			<div class="inner">
				<Composer onsend={(text, a) => send(text, a)} onstop={stop} {busy} bind:mode bind:value={draft} bind:attachments autofocus />
				<p class="disclaimer">{t('chat.disclaimer')}</p>
			</div>
		</div>
	</section>
</div>

<style>
	.chat {
		position: relative;
		display: flex;
		height: 100%;
	}
	.scrim {
		position: absolute;
		inset: 0;
		z-index: 19;
		background: rgba(3, 6, 10, 0.45);
		animation: scrim-in 0.2s ease-out both;
	}
	@keyframes scrim-in {
		from {
			opacity: 0;
		}
	}
	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		margin: -1px;
		padding: 0;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
		border: 0;
	}
	.jump {
		position: absolute;
		left: 50%;
		bottom: calc(100% + 6px);
		transform: translateX(-50%);
		z-index: 5;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		height: 34px;
		padding: 0 14px 0 11px;
		border-radius: 999px;
		border: 1px solid var(--line-2);
		box-shadow: var(--shadow-2);
		background: color-mix(in oklab, var(--surface) 94%, transparent);
		color: var(--text);
		font-size: 0.82rem;
		font-weight: 600;
		animation: jump-in 0.22s var(--ease-out-soft) both;
	}
	.jump:hover {
		border-color: var(--accent-line);
	}
	@keyframes jump-in {
		from {
			opacity: 0;
			transform: translate(-50%, 6px);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.scrim,
		.jump {
			animation: none;
		}
	}
	:global([data-motion='reduced']) .scrim,
	:global([data-motion='reduced']) .jump {
		animation: none;
	}
	.list {
		width: 0;
		overflow: hidden;
		flex: none;
		display: flex;
		flex-direction: column;
		border-right: 1px solid transparent;
		transition: width 0.28s var(--ease-out-soft);
	}
	.chat.side .list {
		width: 290px;
		border-right-color: var(--line);
	}
	.lhead {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 12px 12px 8px 14px;
		width: 290px;
	}
	.new {
		flex: 1;
	}
	.lsearch {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 4px 14px 8px;
		padding: 0 12px;
		height: 36px;
		border-radius: 12px;
		background: var(--surface);
		border: 1px solid var(--line);
		color: var(--text-3);
		width: 262px;
	}
	.lsearch input {
		flex: 1;
		min-width: 0;
		border: 0;
		background: none;
		font-size: 0.86rem;
		color: var(--text);
	}
	.folders {
		display: flex;
		gap: 6px;
		overflow-x: auto;
		scrollbar-width: none;
		margin: 0 14px 6px;
		width: 262px;
	}
	.folders button {
		flex: none;
		display: inline-flex;
		align-items: center;
		gap: 5px;
		height: 28px;
		padding: 0 10px;
		border-radius: 999px;
		font-size: 0.76rem;
		font-weight: 550;
		color: var(--text-3);
		border: 1px solid var(--line);
		white-space: nowrap;
	}
	.folders button:hover {
		color: var(--text);
	}
	.folders button.on {
		color: var(--accent);
		border-color: var(--accent-line);
		background: var(--accent-soft);
	}
	.nf {
		height: 34px;
		margin: 4px 2px 2px;
		font-size: 0.82rem;
		width: calc(100% - 4px);
	}
	.cmenu :global(.ck) {
		margin-left: auto;
		color: var(--accent);
	}
	.items {
		flex: 1;
		overflow-y: auto;
		padding: 4px 8px 16px;
		width: 290px;
	}
	.it {
		position: relative;
		display: flex;
		align-items: center;
		border-radius: 12px;
		transition: background 0.15s;
	}
	.it:hover,
	.it.on {
		background: var(--surface);
	}
	.it.on {
		box-shadow: inset 2px 0 0 var(--accent);
	}
	.il {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 9px 4px 9px 12px;
	}
	.it-title {
		font-size: 0.88rem;
		font-weight: 550;
		display: flex;
		align-items: center;
		gap: 5px;
		min-width: 0;
	}
	/* The text needs its own box: an ellipsis never applies to a flex container's text. */
	.tt {
		min-width: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.it-title :global(.pin) {
		color: var(--accent);
		flex: none;
	}
	.it-sub {
		font-size: 0.74rem;
		color: var(--text-3);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.more {
		opacity: 0;
		margin-right: 4px;
	}
	.it:hover .more,
	.it.on .more,
	.it:focus-within .more,
	.more[aria-expanded='true'],
	:global([data-input='touch']) .more {
		opacity: 1;
	}
	/* No hover on touch screens: the options button must stay reachable. */
	@media (hover: none), (pointer: coarse) {
		.more {
			opacity: 1;
		}
	}
	.cmenu {
		position: absolute;
		right: 8px;
		top: 100%;
		z-index: 30;
		min-width: 160px;
		padding: 5px;
		border-radius: 14px;
		border: 1px solid var(--line-2);
		box-shadow: var(--shadow-2);
		display: flex;
		flex-direction: column;
		background: color-mix(in oklab, var(--surface) 97%, transparent);
	}
	.cmenu button,
	.cmenu a {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 10px;
		border-radius: 9px;
		font-size: 0.85rem;
		color: var(--text-2);
		text-align: left;
	}
	.cmenu button:hover,
	.cmenu a:hover {
		background: var(--surface-3);
		color: var(--text);
	}
	.cmenu .danger {
		color: var(--danger);
	}
	.rn {
		height: 36px;
		margin: 4px;
	}
	.empty-list {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 8px;
		padding: 40px 16px;
		color: var(--text-3);
		font-size: 0.85rem;
		text-align: center;
	}
	.thread {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
	}
	.thead {
		display: flex;
		align-items: center;
		gap: 8px;
		height: 48px;
		padding: 0 16px;
		flex: none;
	}
	.ttl {
		flex: 1;
		font-size: 0.95rem;
		font-weight: 600;
		margin: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		color: var(--text-2);
		text-align: center;
	}
	.scroll {
		flex: 1;
		overflow-y: auto;
		overscroll-behavior: contain;
	}
	.inner {
		max-width: 800px;
		margin: 0 auto;
		padding: 0 clamp(16px, 3vw, 32px);
	}
	.scroll .inner {
		padding-bottom: 28px;
	}
	.hello {
		display: flex;
		flex-direction: column;
		align-items: center;
		text-align: center;
		padding: 7vh 0 20px;
	}
	.hello h2 {
		font-size: 1.9rem;
		font-weight: 620;
		letter-spacing: -0.03em;
		margin: 8px 0 4px;
	}
	.hello p {
		color: var(--text-2);
		margin: 0 0 22px;
	}
	.sugg {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		justify-content: center;
		max-width: 620px;
	}
	.sugg .chip {
		/* One line keeps the 2.3rem pill; a long suggestion (they run longer in Spanish and
		   French) wraps instead of running off a phone screen. */
		height: auto;
		min-height: 2.3rem;
		max-width: 100%;
		padding: 0.3rem 1rem;
		font-size: 0.86rem;
		white-space: normal;
		text-align: center;
	}
	.compose {
		position: relative;
		flex: none;
		padding: 8px 0 12px;
		background: linear-gradient(transparent, var(--bg) 30%);
	}
	.disclaimer {
		text-align: center;
		color: var(--text-3);
		font-size: 0.72rem;
		margin: 8px 0 0;
	}
	@media (max-width: 1100px) {
		.chat.side .list {
			position: absolute;
			z-index: 20;
			height: 100%;
			background: var(--bg-2);
			box-shadow: var(--shadow-2);
		}
	}
</style>
