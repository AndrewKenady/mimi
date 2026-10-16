<script lang="ts">
	import { goto } from '$app/navigation';
	import { fade, scale } from 'svelte/transition';
	import { app } from '$lib/app.svelte';
	import { get } from '$lib/api';
	import { toggleFullscreen } from '$lib/host';
	import { SETTINGS_SECTIONS } from '$lib/settings-sections';
	import { Search, House, MessageSquarePlus, Library, Map, AudioLines, ScanText, Brain, Settings, Moon, Maximize, QrCode, MessagesSquare, CornerDownLeft, NotebookPen } from '@lucide/svelte';

	type Item = { id: string; label: string; hint?: string; icon: any; run: () => void; group: string; keys?: string; owner?: boolean };
	let q = $state('');
	let sel = $state(0);
	let chats = $state<any[]>([]);
	let input: HTMLInputElement | undefined = $state();
	let timer: ReturnType<typeof setTimeout>;
	let opener: HTMLElement | null = null;
	const uid = $props.id();
	const optId = (i: number) => `${uid}-opt-${i}`;

	const base: Item[] = [
		{ id: 'new', label: 'New chat', icon: MessageSquarePlus, run: () => goto('/chat'), group: 'Go' },
		{ id: 'talk', label: 'Talk to Mimi', hint: 'Voice', icon: AudioLines, run: () => (app.voice = true), group: 'Go' },
		{ id: 'home', label: 'Home', icon: House, run: () => goto('/'), group: 'Go' },
		{ id: 'lib', label: 'Library', icon: Library, run: () => goto('/library'), group: 'Go' },
		{ id: 'map', label: 'Map', icon: Map, run: () => goto('/map'), group: 'Go' },
		{ id: 'scribe', label: 'Scribe — record a note', icon: NotebookPen, run: () => goto('/scribe'), group: 'Go' },
		{ id: 'lens', label: 'Lens — read a photo', icon: ScanText, run: () => goto('/lens'), group: 'Go' },
		{ id: 'memory', label: 'Memory', icon: Brain, run: () => goto('/memory'), group: 'Go' },
		{ id: 'settings', label: 'Settings', icon: Settings, run: () => goto('/settings'), group: 'Go' },
		...SETTINGS_SECTIONS.map((s) => ({
			id: 'set-' + s.id,
			label: `Settings: ${s.label}`,
			icon: s.icon,
			run: () => goto('/settings/' + s.id),
			group: 'Settings',
			keys: s.keys,
			owner: s.owner
		})),
		{
			id: 'theme',
			label: 'Toggle light / dark',
			icon: Moon,
			run: () => app.setSetting('user', 'appearance', { theme: app.settings.user?.appearance?.theme === 'light' ? 'dark' : 'light' }),
			group: 'Actions'
		},
		{ id: 'fs', label: 'Toggle full screen', hint: 'F11', icon: Maximize, run: () => toggleFullscreen(), group: 'Actions' },
		{ id: 'share', label: 'Share Mimi with nearby phones', icon: QrCode, run: () => goto('/settings/sharing'), group: 'Actions' }
	];

	const items = $derived.by(() => {
		const needle = q.trim().toLowerCase();
		const list = base.filter(
			(i) => (!i.owner || app.isOwner) && (!needle || i.label.toLowerCase().includes(needle) || (needle.length > 2 && !!i.keys?.includes(needle)))
		);
		const chatItems: Item[] = chats.map((c) => ({ id: c.id, label: c.title || 'Untitled chat', hint: 'Chat', icon: MessagesSquare, run: () => goto('/chat/' + c.id), group: 'Chats' }));
		if (needle.length > 1)
			list.push({ id: 'ask', label: `Ask Mimi: “${q.trim()}”`, icon: Search, run: () => { app.ask(q.trim()); goto('/chat'); }, group: 'Ask' });
		return [...list, ...chatItems];
	});

	const groups = $derived.by(() => {
		const out: { name: string; items: { it: Item; i: number }[] }[] = [];
		items.forEach((it, i) => {
			if (!out.length || out[out.length - 1].name !== it.group) out.push({ name: it.group, items: [] });
			out[out.length - 1].items.push({ it, i });
		});
		return out;
	});

	let wasOpen = false;
	$effect(() => {
		const open = app.palette;
		if (open && !wasOpen) {
			// Remember what had focus, to give it back when the dialog closes.
			opener = document.activeElement instanceof HTMLElement && document.activeElement !== document.body ? document.activeElement : null;
			q = '';
			sel = 0;
			setTimeout(() => input?.focus(), 30);
			get('/api/chats').then((r) => (chats = r.chats.slice(0, 6))).catch(() => {});
		} else if (!open && wasOpen) {
			const back = opener;
			opener = null;
			// A command that navigated moves focus itself; otherwise return to where the user was.
			setTimeout(() => {
				if (back?.isConnected && (document.activeElement === document.body || !document.activeElement)) back.focus({ preventScroll: true });
			}, 40);
		}
		wasOpen = open;
	});

	// Keep the active option in view as the arrow keys move through the list.
	$effect(() => {
		if (!app.palette) return;
		document.getElementById(optId(sel))?.scrollIntoView({ block: 'nearest' });
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
		} else if (e.key === 'Home' && e.ctrlKey) {
			e.preventDefault();
			sel = 0;
		} else if (e.key === 'End' && e.ctrlKey) {
			e.preventDefault();
			sel = Math.max(0, items.length - 1);
		} else if (e.key === 'Enter' && items[sel]) {
			e.preventDefault();
			run(items[sel]);
		}
	}

	// A modal dialog keeps focus inside: the search box is its only tab stop
	// (options are reached with the arrow keys, as in any combobox).
	function trap(e: KeyboardEvent) {
		if (e.key === 'Tab') {
			e.preventDefault();
			input?.focus();
		}
	}
</script>

{#if app.palette}
	<div class="scrim" transition:fade={{ duration: 140 }} onclick={() => (app.palette = false)} role="presentation"></div>
	<div
		class="pal glass"
		data-layer
		role="dialog"
		aria-modal="true"
		aria-label="Command palette"
		tabindex="-1"
		onkeydown={trap}
		transition:scale={{ start: 0.97, duration: 180 }}
	>
		<div class="search">
			<Search size={18} aria-hidden="true" />
			<input
				bind:this={input}
				bind:value={q}
				oninput={onInput}
				onkeydown={onKey}
				placeholder="Search chats, go anywhere, or ask…"
				role="combobox"
				aria-label="Search chats, places and commands"
				aria-expanded="true"
				aria-controls="{uid}-list"
				aria-autocomplete="list"
				aria-activedescendant={items[sel] ? optId(sel) : undefined}
				autocomplete="off"
				spellcheck="false"
			/>
			<kbd aria-hidden="true">Esc</kbd>
		</div>
		<div class="list" id="{uid}-list" role="listbox" aria-label="Results">
			{#each groups as g (g.name)}
				<div role="group" aria-labelledby="{uid}-g-{g.name}">
					<div class="group" id="{uid}-g-{g.name}" role="presentation">{g.name}</div>
					{#each g.items as { it, i } (it.id)}
						{@const Icon = it.icon}
						<!-- Options are driven from the combobox (aria-activedescendant), so they are not tab stops. -->
						<!-- svelte-ignore a11y_click_events_have_key_events -->
						<div
							class="row"
							id={optId(i)}
							role="option"
							tabindex="-1"
							aria-selected={i === sel}
							class:sel={i === sel}
							onmouseenter={() => (sel = i)}
							onclick={() => run(it)}
						>
							<Icon size={17} strokeWidth={1.8} aria-hidden="true" />
							<span class="lbl">{it.label}</span>
							{#if it.hint}<span class="hint">{it.hint}</span>{/if}
							{#if i === sel}<CornerDownLeft size={14} class="enter" aria-hidden="true" />{/if}
						</div>
					{/each}
				</div>
			{:else}
				<div class="none" role="presentation">Nothing matches “{q}”.</div>
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
	.row {
		cursor: pointer;
	}
	.row.sel {
		background: var(--surface-3);
		color: var(--text);
	}
	.none {
		padding: 18px 12px;
		color: var(--text-3);
		font-size: 0.9rem;
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
