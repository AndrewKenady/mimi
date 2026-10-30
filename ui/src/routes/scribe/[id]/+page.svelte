<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { app } from '#lib/app.svelte.js';
	import { del, get, patch } from '#lib/api.js';
	import { fmtDate, t } from '#lib/i18n/index.svelte.js';
	import { ArrowLeft, Sparkles, Download, Trash2, Loader, CircleCheck, ListChecks, Lightbulb, FileText, Pencil } from '@lucide/svelte';

	let note = $state<any>(null);
	let audio: HTMLAudioElement | undefined = $state();
	let current = $state(0);
	let editingTitle = $state(false);
	let title = $state('');

	async function load() {
		note = await get(`/api/scribe/${page.params.id}`).catch(() => null);
		title = note?.title || '';
	}
	onMount(() => {
		load();
		const h = (e: Event) => {
			const d = (e as CustomEvent).detail;
			if (d.id !== page.params.id) return;
			if (d.status === 'ready' || d.status === 'error') load();
			else note = { ...note, ...d };
		};
		addEventListener('mimi:scribe', h);
		return () => removeEventListener('mimi:scribe', h);
	});

	const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
	function seek(t: number) {
		if (audio) {
			audio.currentTime = t;
			audio.play();
		}
	}
	async function saveTitle() {
		editingTitle = false;
		if (title.trim() && title !== note.title) note = await patch(`/api/scribe/${note.id}`, { title: title.trim() });
	}
	// Deleting a recording is reversible for a few seconds: back to the list with an Undo
	// toast; the recording is only deleted once the Undo has gone.
	function remove() {
		const id = note.id;
		app.deferDelete({
			key: `scribe:${id}`,
			text: t('scribe.deleted', { title: note.title }),
			commit: () => del(`/api/scribe/${id}`),
			onUndo: () => goto(`/scribe/${id}`)
		});
		goto('/scribe');
	}
	function ask() {
		app.ask(t('scribe.askNote', { title: note.title }));
		goto('/chat');
	}
</script>

<svelte:head><title>{note?.title || t('scribe.note')} · Mimi</title></svelte:head>

<div class="page">
	<div class="page-inner narrow">
		<a href="/scribe" class="back"><ArrowLeft size={16} /> Scribe</a>
		{#if !note}
			<div class="shimmer" style="height:40px;width:60%;margin-top:12px"></div>
		{:else}
			<header>
				{#if editingTitle}
					<!-- svelte-ignore a11y_autofocus (the user just asked to rename) -->
					<input class="input titlein" bind:value={title} onblur={saveTitle} onkeydown={(e) => e.key === 'Enter' && saveTitle()} aria-label={t('scribe.noteTitle')} autofocus />
				{:else}
					<div class="title-row">
						<h1 class="page-title">{note.title}</h1>
						<button class="icon-btn sm" onclick={() => (editingTitle = true)} aria-label={t('scribe.renameNote')} title={t('scribe.rename')}><Pencil size={15} aria-hidden="true" /></button>
					</div>
				{/if}
				<!-- One string: Svelte trims whitespace at the edge of {#if} blocks, which ate the space before "·". -->
				<p class="page-sub">{[fmtDate(note.created_at * 1000, { dateStyle: 'medium', timeStyle: 'short' }), note.duration ? fmt(note.duration) : ''].filter(Boolean).join(' · ')}</p>
				<div class="acts">
					{#if note.status === 'ready'}
						<button class="btn btn-sm btn-primary" onclick={ask}><Sparkles size={14} /> {t('scribe.askMimi')}</button>
						<a class="btn btn-sm" href="/api/scribe/{note.id}/export" download><Download size={14} /> {t('scribe.export')}</a>
					{/if}
					<button class="btn btn-sm btn-ghost" onclick={remove}><Trash2 size={14} /> {t('scribe.delete')}</button>
				</div>
			</header>

			{#if note.audio_url}
				<audio bind:this={audio} src={note.audio_url} controls preload="metadata" ontimeupdate={() => (current = audio?.currentTime || 0)}></audio>
			{/if}

			{#if note.status !== 'ready' && note.status !== 'error'}
				<div class="working card">
					<Loader size={18} class="spin" />
					<span>{note.status === 'summarizing' ? t('scribe.summarizing') : note.status === 'queued' ? t('scribe.queued') : t('scribe.transcribing')}</span>
					<span class="prog"><span style="width:{Math.max(4, (note.progress || 0) * 100)}%"></span></span>
				</div>
			{:else if note.status === 'error'}
				<div class="working card err">{note.error}</div>
			{/if}

			{#if note.summary}
				<section class="sum card">
					{#if note.summary.summary}<p class="lead">{note.summary.summary}</p>{/if}
					{#if note.summary.key_points?.length}
						<h3><Lightbulb size={16} /> {t('scribe.keyPoints')}</h3>
						<ul class="bullets">{#each note.summary.key_points as p}<li>{p}</li>{/each}</ul>
					{/if}
					{#if note.summary.action_items?.length}
						<h3><ListChecks size={16} /> {t('scribe.actionItems')}</h3>
						<ul class="todo">{#each note.summary.action_items as p}<li><CircleCheck size={15} /> {p}</li>{/each}</ul>
					{/if}
				</section>
			{/if}

			{#if note.transcript?.length}
				<h2 class="label" style="margin:28px 0 10px"><FileText size={13} /> {t('scribe.transcript')}</h2>
				<div class="transcript selectable">
					{#each note.transcript as s, i (i)}
						<p class:now={current >= s.start && current < s.end}>
							<button class="ts" onclick={() => seek(s.start)} aria-label={t('scribe.playFrom', { time: fmt(s.start) })}>{fmt(s.start)}</button>
							<span>{s.text}</span>
						</p>
					{/each}
				</div>
			{/if}
		{/if}
	</div>
</div>

<style>
	.narrow {
		max-width: 820px;
	}
	.back {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1-5);
		color: var(--text-3);
		font-size: var(--fs-md);
	}
	.back:hover {
		color: var(--accent);
	}
	header {
		margin: var(--space-3) 0 var(--space-4);
	}
	.title-row {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.titlein {
		font-size: var(--fs-2xl);
		height: 3rem;
		font-weight: var(--fw-semibold);
	}
	.acts {
		display: flex;
		gap: var(--space-2);
		flex-wrap: wrap;
		margin-top: var(--space-3);
	}
	audio {
		width: 100%;
		margin-bottom: var(--space-4);
		border-radius: var(--radius-md);
	}
	.working {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-4) var(--space-4);
		color: var(--text-2);
		flex-wrap: wrap;
	}
	.working.err {
		color: var(--danger);
	}
	.working :global(.spin) {
		animation: spin 1s linear infinite;
		color: var(--accent);
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	.prog {
		flex-basis: 100%;
		height: 4px;
		border-radius: var(--radius-xs);
		background: var(--surface-3);
		overflow: hidden;
	}
	.prog span {
		display: block;
		height: 100%;
		background: var(--accent);
		transition: width var(--dur-slower);
	}
	.sum {
		padding: var(--space-5) var(--space-6);
	}
	.lead {
		font-size: var(--fs-lg);
		line-height: 1.6;
		margin: 0 0 var(--space-2);
	}
	.sum h3 {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--fs-base);
		margin: var(--space-4) 0 var(--space-2);
		color: var(--text-2);
	}
	.sum h3 :global(svg) {
		color: var(--accent);
	}
	.sum ul {
		margin: 0;
		padding-left: 1.2em;
		line-height: 1.6;
	}
	.todo {
		list-style: none;
		padding: 0 !important;
	}
	.todo li {
		display: flex;
		gap: var(--space-2);
		align-items: flex-start;
		margin: var(--space-1-5) 0;
	}
	.todo :global(svg) {
		color: var(--text-3);
		flex: none;
		margin-top: var(--space-1);
	}
	.label {
		display: flex;
		align-items: center;
		gap: var(--space-1-5);
	}
	.transcript p {
		display: flex;
		gap: var(--space-3);
		margin: 0;
		padding: var(--space-1-5) var(--space-2);
		border-radius: var(--radius-sm);
		line-height: 1.6;
	}
	.transcript p.now {
		background: var(--accent-soft);
	}
	.ts {
		font-variant-numeric: tabular-nums;
		color: var(--accent);
		font-size: var(--fs-sm);
		padding-top: var(--space-0-5);
		flex: none;
		width: 44px;
		text-align: left;
	}
</style>
