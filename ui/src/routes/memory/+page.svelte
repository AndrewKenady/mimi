<script lang="ts">
	import { onMount } from 'svelte';
	import { app } from '$lib/app.svelte';
	import { del, get, patch, post, timeAgo } from '$lib/api';
	import { confirmDialog } from '$lib/confirm.svelte';
	import { t, type Key } from '$lib/i18n/index.svelte';
	import Segmented from '$components/settings/Segmented.svelte';
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
	let filter = $state<string>('all');

	const CATS: Record<string, Key> = { personal: 'memory.catPersonal', preference: 'memory.catPreference', project: 'memory.catProject', other: 'memory.catOther' };

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

	// Memories with an Undo still showing are hidden, not yet deleted.
	const live = $derived(items.filter((m) => !app.isPending(`memory:${m.id}`)));
	const suggested = $derived(live.filter((m) => m.status === 'suggested'));
	const active = $derived(live.filter((m) => m.status === 'active' && (filter === 'all' || m.category === filter)));
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
	// One memory at a time is reversible: it disappears with an Undo, and is only
	// deleted once the Undo has gone.
	function remove(m: any, text = t('memory.forgotten')) {
		app.deferDelete({ key: `memory:${m.id}`, text, commit: () => del(`/api/memories/${m.id}`), onDone: load });
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
	// Everything at once can't be undone: ask first.
	async function wipe() {
		const ok = await confirmDialog({
			title: t('memory.wipeTitle'),
			body: t('memory.wipeBody', { n: items.length }),
			confirmLabel: t('memory.wipeConfirm'),
			tone: 'danger'
		});
		if (!ok) return;
		await del('/api/memories');
		app.toast(t('memory.wiped'), 'ok');
		load();
	}
</script>

<svelte:head><title>{t('memory.pageTitle')}</title></svelte:head>

<div class="page">
	<div class="page-inner narrow">
		<header class="head">
			<div>
				<h1 class="page-title">{t('memory.heading')}</h1>
				<p class="page-sub">{t('memory.intro')}</p>
			</div>
		</header>

		<section class="controls card" aria-label={t('memory.settingsLabel')}>
			<Segmented
				label={t('memory.modeLabel')}
				value={mode}
				options={[
					['ask', t('memory.modeAsk')],
					['auto', t('memory.modeAuto')],
					['off', t('memory.modeOff')]
				]}
				onchange={setMode}
			/>
			<p class="explain" aria-live="polite">
				{#if mode === 'ask'}{t('memory.explainAsk')}{:else if mode === 'auto'}{t('memory.explainAuto')}{:else}{t('memory.explainOff')}{/if}
			</p>
			<div class="row">
				<button class="btn btn-sm" onclick={togglePause} disabled={mode === 'off'}>{#if paused}<Play size={14} aria-hidden="true" /> {t('memory.resume')}{:else}<Pause size={14} aria-hidden="true" /> {t('memory.pause')}{/if}</button>
				<a class="btn btn-sm btn-ghost" href="/api/memories/export?format=md" download><Download size={14} aria-hidden="true" /> {t('memory.export')}</a>
				<span class="grow"></span>
				{#if items.length}
					<button class="btn btn-sm btn-ghost danger" onclick={wipe}><Trash2 size={14} aria-hidden="true" /> {t('memory.eraseAll')}</button>
				{/if}
			</div>
			{#if paused}<p class="paused" role="status"><Pause size={14} aria-hidden="true" /> {t('memory.pausedNote')}</p>{/if}
		</section>

		{#if suggested.length}
			<h2 class="label sect">{t('memory.waiting')}</h2>
			<ul class="list">
				{#each suggested as m (m.id)}
					<li class="mem card sug">
						<Brain size={17} class="mi" aria-hidden="true" />
						<span class="mt">{m.text}</span>
						<button class="btn btn-sm btn-primary" onclick={() => accept(m)} aria-label={t('memory.keepItem', { text: m.text })}><Check size={14} aria-hidden="true" /> {t('memory.keep')}</button>
						<button class="icon-btn sm" onclick={() => remove(m, t('memory.discarded'))} aria-label={t('memory.discardItem', { text: m.text })} title={t('memory.discard')}><X size={15} aria-hidden="true" /></button>
					</li>
				{/each}
			</ul>
		{/if}

		<div class="toolbar">
			<label class="search">
				<Search size={15} aria-hidden="true" />
				<span class="sr-only">{t('memory.search')}</span>
				<input type="search" placeholder={t('memory.searchPlaceholder')} bind:value={q} oninput={load} />
			</label>
			<div class="filters" role="group" aria-label={t('memory.show')}>
				<button class="chip" aria-pressed={filter === 'all'} onclick={() => (filter = 'all')}>{t('memory.all')}</button>
				{#each Object.entries(CATS) as [k, l]}<button class="chip" aria-pressed={filter === k} onclick={() => (filter = k)}>{t(l)}</button>{/each}
			</div>
			<button class="btn btn-sm btn-primary" onclick={() => (adding = !adding)} aria-expanded={adding}><Plus size={15} aria-hidden="true" /> {t('memory.add')}</button>
		</div>

		{#if adding}
			<form
				class="add card"
				onsubmit={(e) => {
					e.preventDefault();
					add();
				}}
			>
				<label class="field grow">
					<span class="field-label">{t('memory.newLabel')}</span>
					<input class="input" placeholder={t('memory.newPlaceholder')} bind:value={newText} data-autofocus />
				</label>
				<label class="field cat">
					<span class="field-label">{t('memory.kind')}</span>
					<select class="input" bind:value={newCat}>{#each Object.entries(CATS) as [k, l]}<option value={k}>{t(l)}</option>{/each}</select>
				</label>
				<button class="btn btn-primary" disabled={!newText.trim()}>{t('memory.save')}</button>
			</form>
		{/if}

		{#each groups as [cat, list] (cat)}
			<h2 class="label sect">{t(CATS[cat])}</h2>
			<ul class="list">
				{#each list as m (m.id)}
					<li class="mem card">
						{#if editId === m.id}
							<label class="field grow">
								<span class="sr-only">{t('memory.editLabel')}</span>
								<input
									class="input"
									bind:value={editText}
									onkeydown={(e) => {
										if (e.key === 'Enter') saveEdit(m);
										if (e.key === 'Escape') editId = null;
									}}
								/>
							</label>
							<button class="btn btn-sm btn-primary" onclick={() => saveEdit(m)}>{t('memory.save')}</button>
							<button class="btn btn-sm btn-ghost" onclick={() => (editId = null)}>{t('memory.cancel')}</button>
						{:else}
							<span class="mt">
								<span>{#if m.pinned}<Pin size={13} class="pin" aria-label={t('memory.pinned')} />{/if}{m.text}</span>
								<small>
									{timeAgo(m.created_at)}{#if m.use_count} · {t('memory.used', { n: m.use_count })}{/if}
									{#if m.source_chat_id} · <a href="/chat/{m.source_chat_id}"><MessagesSquare size={11} aria-hidden="true" /> {t('memory.fromChat')}</a>{/if}
								</small>
							</span>
							<button class="icon-btn sm" onclick={() => pin(m)} title={m.pinned ? t('memory.unpin') : t('memory.alwaysUse')} aria-label={m.pinned ? t('memory.unpin') : t('memory.pinItem')} aria-pressed={!!m.pinned}>{#if m.pinned}<PinOff size={15} aria-hidden="true" />{:else}<Pin size={15} aria-hidden="true" />{/if}</button>
							<button
								class="icon-btn sm"
								onclick={() => {
									editId = m.id;
									editText = m.text;
								}}
								aria-label={t('memory.editItem', { text: m.text })}
								title={t('memory.edit')}><Pencil size={15} aria-hidden="true" /></button
							>
							<button class="icon-btn sm" onclick={() => remove(m)} aria-label={t('memory.forgetItem', { text: m.text })} title={t('memory.forget')}><Trash2 size={15} aria-hidden="true" /></button>
						{/if}
					</li>
				{/each}
			</ul>
		{:else}
			{#if !loading && !suggested.length}
				<div class="empty">
					<Brain size={28} aria-hidden="true" />
					<p>{t('memory.emptyBefore')}<i>{t('memory.emptyExample')}</i>{t('memory.emptyAfter')}</p>
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
		margin-bottom: var(--space-5);
	}
	.controls {
		padding: var(--space-4) var(--space-5);
	}
	.explain {
		color: var(--text-2);
		margin: var(--space-3) 0;
		font-size: var(--fs-md);
		line-height: var(--lh-md);
	}
	.row {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex-wrap: wrap;
	}
	.grow {
		flex: 1;
	}
	.danger {
		color: var(--danger) !important;
	}
	.paused {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin: var(--space-3) 0 0;
		color: var(--warn);
		font-size: var(--fs-md);
	}
	.sect {
		margin: var(--space-6) 0 var(--space-2);
	}
	.toolbar {
		display: flex;
		gap: var(--space-2);
		align-items: center;
		flex-wrap: wrap;
		margin-top: var(--space-6);
	}
	.search {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		height: var(--control-md);
		padding: 0 var(--space-3);
		border-radius: var(--radius-md);
		background: var(--surface);
		border: 1px solid var(--line-2);
		color: var(--text-3);
		width: 220px;
	}
	.search:focus-within {
		border-color: var(--accent);
	}
	.search input {
		border: 0;
		background: none;
		flex: 1;
		min-width: 0;
		height: 100%;
		color: var(--text);
	}
	.filters {
		display: flex;
		gap: var(--space-1-5);
		flex: 1;
		flex-wrap: wrap;
	}
	.add {
		display: flex;
		gap: var(--space-2);
		align-items: flex-end;
		flex-wrap: wrap;
		padding: var(--space-3);
		margin-top: var(--space-3);
	}
	.add .grow {
		min-width: 220px;
	}
	.add .cat {
		/* 170px, or wider when a kind's name needs it ("À propos de vous") */
		width: auto;
		min-width: 170px;
	}
	.list {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.mem {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-3) var(--space-3) var(--space-3) var(--space-4);
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
		gap: var(--space-0-5);
		line-height: var(--lh-md);
	}
	.mt :global(.pin) {
		color: var(--accent);
		display: inline;
		margin-right: var(--space-1-5);
		vertical-align: -1px;
	}
	.mt small {
		color: var(--text-3);
		font-size: var(--fs-xs);
	}
	.mt small a {
		color: var(--text-2);
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		text-decoration: underline;
		text-decoration-color: var(--line-2);
		text-underline-offset: 2px;
	}
	.mt small a:hover {
		color: var(--accent);
	}
	.empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-3);
		text-align: center;
		color: var(--text-3);
		padding: var(--space-12) var(--space-5);
	}
	.empty p {
		max-width: 440px;
		color: var(--text-2);
		margin: 0;
	}
</style>
