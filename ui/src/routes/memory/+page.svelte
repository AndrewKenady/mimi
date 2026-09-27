<script lang="ts">
	import { onMount } from 'svelte';
	import { app } from '$lib/app.svelte';
	import { del, get, patch, post, timeAgo } from '$lib/api';
	import { Brain, Pin, PinOff, Trash2, Check, X, Plus, Search, Download, Pause, Play, Pencil, MessagesSquare } from '@lucide/svelte';

	let items = $state<any[]>([]);
	let mode = $state('ask');
	let paused = $state(false);
	let loading = $state(true);
	let q = $state('');
	let adding = $state(false);
	let newText = $state('');
	let newCat = $state('personal');
	let editId = $state<string | null>(null);
	let editText = $state('');
	let confirmWipe = $state(false);
	let filter = $state<string>('all');

	const CATS: Record<string, string> = { personal: 'About you', preference: 'Preferences', project: 'Projects', other: 'Other' };

	async function load() {
		try {
			const r = await get(`/api/memories${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ''}`);
			items = r.memories;
			mode = r.mode === 'off' && !r.paused ? 'off' : app.settings.user?.privacy?.memory || 'ask';
			paused = r.paused;
		} finally {
			loading = false;
		}
	}
	onMount(load);
	$effect(() => {
		app.memoryVersion;
		load();
	});

	const suggested = $derived(items.filter((m) => m.status === 'suggested'));
	const active = $derived(items.filter((m) => m.status === 'active' && (filter === 'all' || m.category === filter)));
	const groups = $derived(Object.keys(CATS).map((c) => [c, active.filter((m) => m.category === c)] as const).filter(([, l]) => l.length));

	async function setMode(m: string) {
		mode = m;
		await app.setSetting('user', 'privacy', { memory: m });
	}
	async function togglePause() {
		paused = !paused;
		await app.setSetting('user', 'privacy', { memory_paused: paused });
	}
	async function add() {
		if (!newText.trim()) return;
		await post('/api/memories', { text: newText.trim(), category: newCat });
		newText = '';
		adding = false;
		load();
	}
	async function accept(m: any) {
		await post(`/api/memories/${m.id}/accept`);
		load();
	}
	async function remove(m: any) {
		await del(`/api/memories/${m.id}`);
		app.toast('Forgotten');
		load();
	}
	async function pin(m: any) {
		await patch(`/api/memories/${m.id}`, { pinned: !m.pinned });
		load();
	}
	async function saveEdit(m: any) {
		if (editText.trim() && editText !== m.text) await patch(`/api/memories/${m.id}`, { text: editText.trim() });
		editId = null;
		load();
	}
	async function wipe() {
		await del('/api/memories');
		confirmWipe = false;
		app.toast('All memories erased', 'ok');
		load();
	}
</script>

<svelte:head><title>Memory · MIMI</title></svelte:head>

<div class="page">
	<div class="page-inner narrow">
		<header class="head">
			<div>
				<h1 class="page-title">Memory</h1>
				<p class="page-sub">What MIMI knows about you, so it can help without asking twice. It stays on this device, and you're in control of every word.</p>
			</div>
		</header>

		<section class="controls card">
			<div class="seg" role="radiogroup" aria-label="Memory mode">
				{#each [['ask', 'Ask first'], ['auto', 'Automatic'], ['off', 'Off']] as [v, l]}
					<button role="radio" aria-checked={mode === v} class:on={mode === v} onclick={() => setMode(v)}>{l}</button>
				{/each}
			</div>
			<p class="explain">
				{#if mode === 'ask'}MIMI suggests things to remember, and you approve each one.{:else if mode === 'auto'}MIMI saves lasting facts on its own. You can review them here.{:else}MIMI won't save or use memories.{/if}
			</p>
			<div class="row">
				<button class="btn btn-sm" onclick={togglePause} disabled={mode === 'off'}>{#if paused}<Play size={14} /> Resume memory{:else}<Pause size={14} /> Pause memory{/if}</button>
				<a class="btn btn-sm btn-ghost" href="/api/memories/export?format=md" download><Download size={14} /> Export</a>
				<span class="grow"></span>
				{#if confirmWipe}
					<span class="confirm">Erase everything? <button class="btn btn-sm btn-danger" onclick={wipe}>Erase</button><button class="btn btn-sm btn-ghost" onclick={() => (confirmWipe = false)}>Cancel</button></span>
				{:else if items.length}
					<button class="btn btn-sm btn-ghost danger" onclick={() => (confirmWipe = true)}><Trash2 size={14} /> Erase all</button>
				{/if}
			</div>
			{#if paused}<p class="paused"><Pause size={14} /> Memory is paused. MIMI isn't using or saving memories right now.</p>{/if}
		</section>

		{#if suggested.length}
			<h2 class="label sect">Waiting for your OK</h2>
			<div class="list">
				{#each suggested as m (m.id)}
					<div class="mem card sug">
						<Brain size={17} class="mi" />
						<span class="mt">{m.text}</span>
						<button class="btn btn-sm btn-primary" onclick={() => accept(m)}><Check size={14} /> Keep</button>
						<button class="icon-btn sm" onclick={() => remove(m)} aria-label="Discard"><X size={15} /></button>
					</div>
				{/each}
			</div>
		{/if}

		<div class="toolbar">
			<div class="search"><Search size={15} /><input placeholder="Search memories" bind:value={q} oninput={load} /></div>
			<div class="filters">
				<button class="chip" class:active={filter === 'all'} onclick={() => (filter = 'all')}>All</button>
				{#each Object.entries(CATS) as [k, l]}<button class="chip" class:active={filter === k} onclick={() => (filter = k)}>{l}</button>{/each}
			</div>
			<button class="btn btn-sm btn-primary" onclick={() => (adding = !adding)}><Plus size={15} /> Add</button>
		</div>

		{#if adding}
			<form class="add card" onsubmit={(e) => { e.preventDefault(); add(); }}>
				<input class="input" placeholder="e.g. I'm allergic to penicillin" bind:value={newText} />
				<select class="input sel" bind:value={newCat}>{#each Object.entries(CATS) as [k, l]}<option value={k}>{l}</option>{/each}</select>
				<button class="btn btn-primary" disabled={!newText.trim()}>Save</button>
			</form>
		{/if}

		{#each groups as [cat, list] (cat)}
			<h2 class="label sect">{CATS[cat]}</h2>
			<div class="list">
				{#each list as m (m.id)}
					<div class="mem card">
						{#if editId === m.id}
							<input class="input" bind:value={editText} onkeydown={(e) => { if (e.key === 'Enter') saveEdit(m); if (e.key === 'Escape') editId = null; }} />
							<button class="btn btn-sm btn-primary" onclick={() => saveEdit(m)}>Save</button>
						{:else}
							<span class="mt">
								{#if m.pinned}<Pin size={13} class="pin" />{/if}{m.text}
								<small>
									{timeAgo(m.created_at)}{#if m.use_count} · used {m.use_count}×{/if}
									{#if m.source_chat_id} · <a href="/chat/{m.source_chat_id}"><MessagesSquare size={11} /> from a chat</a>{/if}
								</small>
							</span>
							<button class="icon-btn sm" onclick={() => pin(m)} title={m.pinned ? 'Unpin' : 'Always use'} aria-label="Pin">{#if m.pinned}<PinOff size={15} />{:else}<Pin size={15} />{/if}</button>
							<button class="icon-btn sm" onclick={() => { editId = m.id; editText = m.text; }} aria-label="Edit"><Pencil size={15} /></button>
							<button class="icon-btn sm" onclick={() => remove(m)} aria-label="Forget"><Trash2 size={15} /></button>
						{/if}
					</div>
				{/each}
			</div>
		{:else}
			{#if !loading && !suggested.length}
				<div class="empty">
					<Brain size={28} />
					<p>No memories yet. Tell MIMI something like <i>“Remember that I drive a 2014 Tacoma”</i>, or add one yourself.</p>
				</div>
			{/if}
		{/each}
	</div>
</div>

<style>
	.narrow {
		max-width: 860px;
	}
	.head {
		margin-bottom: 20px;
	}
	.controls {
		padding: 18px 20px;
	}
	.seg {
		display: inline-flex;
		padding: 4px;
		border-radius: 999px;
		background: var(--surface-2);
		border: 1px solid var(--line);
	}
	.seg button {
		height: 36px;
		padding: 0 18px;
		border-radius: 999px;
		color: var(--text-2);
		font-weight: 550;
		font-size: 0.88rem;
	}
	.seg button.on {
		background: var(--accent);
		color: var(--accent-ink);
	}
	.explain {
		color: var(--text-2);
		margin: 12px 0 14px;
		font-size: 0.92rem;
	}
	.row {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}
	.grow {
		flex: 1;
	}
	.danger {
		color: var(--danger) !important;
	}
	.confirm {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		font-size: 0.88rem;
		color: var(--text-2);
	}
	.paused {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 12px 0 0;
		color: var(--warn);
		font-size: 0.86rem;
	}
	.sect {
		margin: 26px 0 10px;
	}
	.toolbar {
		display: flex;
		gap: 10px;
		align-items: center;
		flex-wrap: wrap;
		margin-top: 26px;
	}
	.search {
		display: flex;
		align-items: center;
		gap: 8px;
		height: 38px;
		padding: 0 12px;
		border-radius: 12px;
		background: var(--surface);
		border: 1px solid var(--line);
		color: var(--text-3);
		width: 220px;
	}
	.search input {
		border: 0;
		background: none;
		flex: 1;
		min-width: 0;
		color: var(--text);
	}
	.filters {
		display: flex;
		gap: 6px;
		flex: 1;
		flex-wrap: wrap;
	}
	.add {
		display: flex;
		gap: 8px;
		padding: 12px;
		margin-top: 12px;
	}
	.sel {
		width: 170px;
	}
	.list {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.mem {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 12px 12px 12px 18px;
	}
	.mem.sug {
		border-color: var(--accent-line);
		background: var(--accent-soft);
	}
	.mem :global(.mi) {
		color: var(--accent);
		flex: none;
	}
	.mt {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
		line-height: 1.45;
	}
	.mt :global(.pin) {
		color: var(--accent);
		display: inline;
		margin-right: 6px;
		vertical-align: -1px;
	}
	.mt small {
		color: var(--text-3);
		font-size: 0.75rem;
	}
	.mt small a {
		color: var(--text-2);
		display: inline-flex;
		align-items: center;
		gap: 3px;
	}
	.mt small a:hover {
		color: var(--accent);
	}
	.empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 10px;
		text-align: center;
		color: var(--text-3);
		padding: 50px 20px;
	}
	.empty p {
		max-width: 440px;
		color: var(--text-2);
		margin: 0;
	}
</style>
