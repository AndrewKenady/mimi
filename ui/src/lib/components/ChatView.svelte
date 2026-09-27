<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount, tick } from 'svelte';
	import { app } from '$lib/app.svelte';
	import { del, get, patch, post, stream, timeAgo } from '$lib/api';
	import { Speaker } from '$lib/audio';
	import Composer from './Composer.svelte';
	import Message from './Message.svelte';
	import Well from './Well.svelte';
	import { SquarePen, Search, Pin, PinOff, Trash2, PanelLeftClose, PanelLeft, Download, Archive, EllipsisVertical, MessagesSquare, Pencil, Folder, FolderInput, ArchiveRestore, Check } from '@lucide/svelte';

	let { id = null }: { id?: string | null } = $props();

	let chat = $state<any>(null);
	let messages = $state<any[]>([]);
	let list = $state<any[]>([]);
	let q = $state('');
	let busy = $state(false);
	let status = $state('');
	let mode = $state(app.settings.user?.assistant?.default_mode || 'everyday');
	let draft = $state('');
	let attachments = $state<any[]>([]);
	let scroller: HTMLDivElement | undefined = $state();
	let stick = true;
	let abort: AbortController | null = null;
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
		app.toast(name.trim() ? `Moved to ${name.trim()}` : 'Removed from folder');
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
			app.toast('That chat no longer exists', 'error');
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
	});

	function onScroll() {
		if (!scroller) return;
		stick = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120;
	}
	function scrollBottom(force = false) {
		if (scroller && (stick || force)) scroller.scrollTop = scroller.scrollHeight;
	}

	async function send(text: string, atts: any[], opts: { regenerate?: string; edit?: string } = {}) {
		if (busy) return;
		busy = true;
		status = 'Thinking…';
		stick = true;
		const readAloud = app.settings.user?.voice?.read_aloud;
		const speaker = readAloud ? new Speaker(app.settings.user?.voice?.voice, app.settings.user?.voice?.speed) : null;
		const live: any = { id: 'live', role: 'assistant', content: '', meta: { tools: [], sources: [], memory_suggested: [] } };
		if (opts.regenerate) {
			const idx = messages.findIndex((x) => x.id === opts.regenerate);
			messages = [...messages.slice(0, idx), live];
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
		try {
			const body = { content: text, attachments: atts.map((a) => a.id), mode, regenerate: opts.regenerate, edit: opts.edit };
			for await (const ev of stream(`/api/chats/${chat?.id || 'new'}/messages`, body, abort.signal)) {
				const d = ev.data;
				if (ev.event === 'meta') {
					if (!chat) {
						chat = { id: d.chat_id, title: d.title };
						loadedId = d.chat_id;
						goto(`/chat/${d.chat_id}`, { replaceState: true, noScroll: true, keepFocus: true });
					}
					const pi = messages.findIndex((x) => x.id === 'pending');
					if (pi >= 0 && d.user_message) messages[pi] = d.user_message;
				} else if (ev.event === 'status') status = d.label;
				else if (ev.event === 'tool') {
					update((m) => {
						const tools = [...m.meta.tools];
						const k = tools.findIndex((t: any) => t.id === d.id);
						if (k >= 0) tools[k] = { ...tools[k], ...d };
						else tools.push(d);
						m.meta.tools = tools;
					});
				} else if (ev.event === 'sources') update((m) => (m.meta.sources = d.sources));
				else if (ev.event === 'memory') {
					update((m) => {
						if (d.used) m.meta.memories_used = d.used;
						if (d.suggested) m.meta.memory_suggested = [...(m.meta.memory_suggested || []), ...d.suggested];
						if (d.saved) app.toast(`Remembered: ${d.saved[0]?.text}`, 'ok');
					});
				} else if (ev.event === 'delta') {
					update((m) => (m.content += d.text));
					speaker?.feed(d.text);
				} else if (ev.event === 'error') {
					update((m) => (m.meta.error = d.message));
				} else if (ev.event === 'done') {
					const i = liveIdx();
					const sugg = i >= 0 ? messages[i].meta.memory_suggested : [];
					const final = { ...d.message, meta: { ...d.message.meta, memory_suggested: sugg } };
					if (i >= 0) messages[i] = final;
					if (d.chat?.title) chat = { ...chat, title: d.chat.title };
					speaker?.flush();
				}
				await tick();
				scrollBottom();
			}
		} catch (e: any) {
			if (e.name !== 'AbortError') update((m) => (m.meta.error = e.message || 'Connection lost'));
		} finally {
			busy = false;
			status = '';
			abort = null;
			loadList();
			// Pull the canonical thread (versions, ids) once streaming is done.
			if (chat?.id) {
				const c = await get(`/api/chats/${chat.id}`).catch(() => null);
				if (c) {
					const sugg = messages.find((x) => x.meta?.memory_suggested?.length)?.meta.memory_suggested;
					messages = c.messages.map((x: any, i: number) => (i === c.messages.length - 1 && sugg ? { ...x, meta: { ...x.meta, memory_suggested: sugg } } : x));
					chat = { ...chat, ...c };
				}
			}
		}
	}

	async function stop() {
		if (chat?.id) await post(`/api/chats/${chat.id}/stop`).catch(() => {});
	}

	async function switchVersion(mid: string) {
		const c = await post(`/api/chats/${chat.id}/head`, { message_id: mid });
		messages = c.messages;
	}

	function newChat() {
		chat = null;
		messages = [];
		loadedId = null;
		goto('/chat');
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
	async function remove(c: any) {
		await del(`/api/chats/${c.id}`);
		menuFor = null;
		if (c.id === chat?.id) newChat();
		loadList();
		app.toast('Chat deleted');
	}
	async function saveRename(c: any) {
		if (renameText.trim()) await patch(`/api/chats/${c.id}`, { title: renameText.trim() });
		renaming = null;
		loadList();
		if (c.id === chat?.id) chat = { ...chat, title: renameText.trim() };
	}

	const lastAssistant = $derived([...messages].reverse().find((x) => x.role === 'assistant'));
	const hour = new Date().getHours();
	const greeting = hour < 5 ? 'Up late' : hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
	const suggestions = [
		'How do I treat a bee sting?',
		'What can I see near here?',
		'Explain how a car battery works',
		'Summarize the history of the Oregon Trail'
	];
</script>

<div class="chat" class:side={sideOpen}>
	<aside class="list" aria-label="Chats">
		<div class="lhead">
			<button class="btn btn-primary new" onclick={newChat}><SquarePen size={16} /> New chat</button>
			<button class="icon-btn" onclick={() => (sideOpen = false)} aria-label="Hide chat list"><PanelLeftClose size={18} /></button>
		</div>
		<div class="lsearch">
			<Search size={15} />
			<input placeholder="Search chats" bind:value={q} oninput={() => loadList()} />
		</div>
		<div class="folders" role="tablist" aria-label="Folders">
			<button role="tab" aria-selected={folder === ''} class:on={folder === ''} onclick={() => pickFolder('')}>All</button>
			{#each projects as p (p)}
				<button role="tab" aria-selected={folder === p} class:on={folder === p} onclick={() => pickFolder(p)}><Folder size={12} /> {p}</button>
			{/each}
			<button role="tab" aria-selected={folder === ARCHIVE} class:on={folder === ARCHIVE} onclick={() => pickFolder(ARCHIVE)}><Archive size={12} /> Archived</button>
		</div>
		<div class="items" data-scroll>
			{#each list as c (c.id)}
				<div class="it" class:on={c.id === chat?.id}>
					{#if renaming === c.id}
						<input class="input rn" bind:value={renameText} onkeydown={(e) => { if (e.key === 'Enter') saveRename(c); if (e.key === 'Escape') renaming = null; }} onblur={() => saveRename(c)} />
					{:else}
						<a href="/chat/{c.id}" class="il">
							<span class="it-title">{#if c.pinned}<Pin size={12} class="pin" />{/if}{c.title || 'New chat'}</span>
							<span class="it-sub">{timeAgo(c.updated_at)}{c.preview ? ' · ' + c.preview : ''}</span>
						</a>
						<button class="icon-btn sm more" onclick={() => { menuFor = menuFor === c.id ? null : c.id; moving = null; }} aria-label="Chat options"><EllipsisVertical size={15} /></button>
						{#if menuFor === c.id && moving === c.id}
							<div class="cmenu glass" role="menu">
								{#each projects as p (p)}
									<button onclick={() => moveTo(c, p)}><Folder size={14} /> {p}{#if c.project === p}<Check size={13} class="ck" />{/if}</button>
								{/each}
								{#if c.project}<button onclick={() => moveTo(c, '')}><FolderInput size={14} /> No folder</button>{/if}
								<input class="input nf" placeholder="New folder…" bind:value={newFolder} onkeydown={(e) => { if (e.key === 'Enter' && newFolder.trim()) moveTo(c, newFolder); if (e.key === 'Escape') moving = null; }} />
							</div>
						{:else if menuFor === c.id}
							<div class="cmenu glass" role="menu">
								<button onclick={() => { renaming = c.id; renameText = c.title; menuFor = null; }}><Pencil size={14} /> Rename</button>
								<button onclick={() => togglePin(c)}>{#if c.pinned}<PinOff size={14} /> Unpin{:else}<Pin size={14} /> Pin{/if}</button>
								<button onclick={() => (moving = c.id)}><FolderInput size={14} /> Move to folder…</button>
								<a href="/api/chats/{c.id}/export" download><Download size={14} /> Export</a>
								{#if c.archived}
									<button onclick={() => unarchive(c)}><ArchiveRestore size={14} /> Unarchive</button>
								{:else}
									<button onclick={() => archive(c)}><Archive size={14} /> Archive</button>
								{/if}
								<button class="danger" onclick={() => remove(c)}><Trash2 size={14} /> Delete</button>
							</div>
						{/if}
					{/if}
				</div>
			{:else}
				<div class="empty-list"><MessagesSquare size={20} /><span>{q ? 'No matching chats' : folder === ARCHIVE ? 'No archived chats' : folder ? 'This folder is empty' : 'Your conversations will appear here'}</span></div>
			{/each}
		</div>
	</aside>

	<section class="thread">
		<header class="thead">
			{#if !sideOpen}<button class="icon-btn" onclick={() => (sideOpen = true)} aria-label="Show chat list"><PanelLeft size={18} /></button>{/if}
			<h1 class="ttl">{chat?.title || (messages.length ? 'New chat' : '')}</h1>
			{#if !sideOpen && messages.length}<button class="icon-btn" onclick={newChat} aria-label="New chat"><SquarePen size={18} /></button>{/if}
		</header>

		<div class="scroll" bind:this={scroller} onscroll={onScroll} data-scroll>
			<div class="inner">
				{#if !messages.length}
					<div class="hello fade-up">
						<Well size={150} mood="idle" />
						<h2>{greeting}{app.me?.role !== 'guest' ? `, ${app.me?.name}` : ''}.</h2>
						<p>Ask me anything. I'll check the offline library and show my sources.</p>
						<div class="sugg">
							{#each suggestions as s}<button class="chip" onclick={() => send(s, [])}>{s}</button>{/each}
						</div>
					</div>
				{/if}
				{#each messages as m (m.id)}
					<Message
						{m}
						live={m.id === 'live'}
						{status}
						onregenerate={m.role === 'assistant' && m === lastAssistant && !busy && m.id !== 'live' ? () => send('', [], { regenerate: m.id }) : undefined}
						onswitch={!busy ? switchVersion : undefined}
						onedit={m.role === 'user' && !busy && m.id !== 'pending' ? (t) => send(t, [], { edit: m.id }) : undefined}
					/>
				{/each}
			</div>
		</div>

		<div class="compose">
			<div class="inner">
				<Composer onsend={(t, a) => send(t, a)} onstop={stop} {busy} bind:mode bind:value={draft} bind:attachments autofocus />
				<p class="disclaimer">Mimi runs offline on this device and can make mistakes. Check important facts in the sources.</p>
			</div>
		</div>
	</section>
</div>

<style>
	.chat {
		display: flex;
		height: 100%;
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
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		display: flex;
		align-items: center;
		gap: 5px;
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
	.more:focus {
		opacity: 1;
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
		height: 2.3rem;
		padding: 0 1rem;
		font-size: 0.86rem;
	}
	.compose {
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
