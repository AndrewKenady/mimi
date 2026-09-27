<script lang="ts">
	import { goto } from '$app/navigation';
	import { fade, scale } from 'svelte/transition';
	import { app } from '$lib/app.svelte';
	import { get } from '$lib/api';
	import { toggleFullscreen } from '$lib/host';
	import { Search, House, MessageSquarePlus, Library, Map, AudioLines, ScanText, Brain, Settings, Mic, Moon, Maximize, QrCode, MessagesSquare, CornerDownLeft, NotebookPen } from '@lucide/svelte';

	type Item = { id: string; label: string; hint?: string; icon: any; run: () => void; group: string };
	let q = $state('');
	let sel = $state(0);
	let chats = $state<any[]>([]);
	let input: HTMLInputElement | undefined = $state();
	let timer: ReturnType<typeof setTimeout>;

	const base: Item[] = [
		{ id: 'new', label: 'New chat', icon: MessageSquarePlus, run: () => goto('/chat'), group: 'Go' },
		{ id: 'talk', label: 'Talk to MIMI', hint: 'Voice', icon: AudioLines, run: () => (app.voice = true), group: 'Go' },
		{ id: 'home', label: 'Home', icon: House, run: () => goto('/'), group: 'Go' },
		{ id: 'lib', label: 'Library', icon: Library, run: () => goto('/library'), group: 'Go' },
		{ id: 'map', label: 'Map', icon: Map, run: () => goto('/map'), group: 'Go' },
		{ id: 'scribe', label: 'Scribe — record a note', icon: NotebookPen, run: () => goto('/scribe'), group: 'Go' },
		{ id: 'lens', label: 'Lens — read a photo', icon: ScanText, run: () => goto('/lens'), group: 'Go' },
		{ id: 'memory', label: 'Memory', icon: Brain, run: () => goto('/memory'), group: 'Go' },
		{ id: 'settings', label: 'Settings', icon: Settings, run: () => goto('/settings'), group: 'Go' },
		...['general', 'appearance', 'assistant', 'models', 'voice', 'library', 'location', 'sharing', 'accounts', 'controls', 'power', 'system'].map((s) => ({
			id: 'set-' + s,
			label: `Settings: ${s[0].toUpperCase() + s.slice(1)}`,
			icon: Settings,
			run: () => goto('/settings/' + s),
			group: 'Settings'
		})),
		{
			id: 'theme',
			label: 'Toggle light / dark',
			icon: Moon,
			run: () => app.setSetting('user', 'appearance', { theme: app.settings.user?.appearance?.theme === 'light' ? 'dark' : 'light' }),
			group: 'Actions'
		},
		{ id: 'fs', label: 'Toggle full screen', hint: 'F11', icon: Maximize, run: () => toggleFullscreen(), group: 'Actions' },
		{ id: 'share', label: 'Share MIMI with nearby phones', icon: QrCode, run: () => goto('/settings/sharing'), group: 'Actions' }
	];

	const items = $derived.by(() => {
		const needle = q.trim().toLowerCase();
		const list = base.filter((i) => !needle || i.label.toLowerCase().includes(needle));
		const chatItems: Item[] = chats.map((c) => ({ id: c.id, label: c.title || 'Untitled chat', hint: 'Chat', icon: MessagesSquare, run: () => goto('/chat/' + c.id), group: 'Chats' }));
		if (needle.length > 1)
			list.push({ id: 'ask', label: `Ask MIMI: “${q.trim()}”`, icon: Search, run: () => { app.ask(q.trim()); goto('/chat'); }, group: 'Ask' });
		return [...list, ...chatItems];
	});

	$effect(() => {
		if (app.palette) {
			q = '';
			sel = 0;
			setTimeout(() => input?.focus(), 30);
			get('/api/chats').then((r) => (chats = r.chats.slice(0, 6))).catch(() => {});
		}
	});

	function onInput() {
		sel = 0;
		clearTimeout(timer);
		timer = setTimeout(async () => {
			try {
				const r = await get(`/api/chats${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ''}`);
				chats = r.chats.slice(0, 8);
			} catch {
				/* ignore */
			}
		}, 160);
	}

	function run(i: Item) {
		app.palette = false;
		i.run();
	}

	function onKey(e: KeyboardEvent) {
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			sel = Math.min(items.length - 1, sel + 1);
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			sel = Math.max(0, sel - 1);
		} else if (e.key === 'Enter' && items[sel]) {
			e.preventDefault();
			run(items[sel]);
		}
	}
</script>

{#if app.palette}
	<div class="scrim" transition:fade={{ duration: 140 }} onclick={() => (app.palette = false)} role="presentation"></div>
	<div class="pal glass" data-layer role="dialog" aria-label="Command palette" transition:scale={{ start: 0.97, duration: 180 }}>
		<div class="search">
			<Search size={18} />
			<input bind:this={input} bind:value={q} oninput={onInput} onkeydown={onKey} placeholder="Search chats, go anywhere, or ask…" />
			<kbd>Esc</kbd>
		</div>
		<div class="list">
			{#each items as it, i (it.id)}
				{#if i === 0 || items[i - 1].group !== it.group}<div class="group">{it.group}</div>{/if}
				{@const Icon = it.icon}
				<button class="row" class:sel={i === sel} onmouseenter={() => (sel = i)} onclick={() => run(it)}>
					<Icon size={17} strokeWidth={1.8} />
					<span class="lbl">{it.label}</span>
					{#if it.hint}<span class="hint">{it.hint}</span>{/if}
					{#if i === sel}<CornerDownLeft size={14} class="enter" />{/if}
				</button>
			{/each}
		</div>
	</div>
{/if}

<style>
	.scrim {
		position: fixed;
		inset: 0;
		background: rgba(3, 6, 10, 0.5);
		z-index: 60;
	}
	.pal {
		position: fixed;
		top: 12vh;
		left: 50%;
		transform: translateX(-50%);
		width: min(640px, calc(100vw - 24px));
		max-height: 70vh;
		display: flex;
		flex-direction: column;
		border-radius: 22px;
		border: 1px solid var(--line-2);
		box-shadow: var(--shadow-2);
		z-index: 61;
		background: color-mix(in oklab, var(--surface) 97%, transparent);
		overflow: hidden;
	}
	.search {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 0 18px;
		height: 60px;
		border-bottom: 1px solid var(--line);
		color: var(--text-3);
	}
	.search input {
		flex: 1;
		background: none;
		border: 0;
		font-size: 1.05rem;
		color: var(--text);
	}
	kbd {
		font-family: var(--font-sans);
		font-size: 0.7rem;
		padding: 3px 7px;
		border-radius: 6px;
		border: 1px solid var(--line-2);
		color: var(--text-3);
	}
	.list {
		overflow-y: auto;
		padding: 6px 8px 10px;
	}
	.group {
		font-size: 0.7rem;
		font-weight: 600;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--text-3);
		padding: 12px 12px 6px;
	}
	.row {
		display: flex;
		align-items: center;
		gap: 12px;
		width: 100%;
		padding: 10px 12px;
		border-radius: 12px;
		color: var(--text-2);
		text-align: left;
	}
	.row.sel {
		background: var(--surface-3);
		color: var(--text);
	}
	.lbl {
		flex: 1;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.hint {
		font-size: 0.76rem;
		color: var(--text-3);
	}
	.row :global(.enter) {
		color: var(--text-3);
	}
</style>
