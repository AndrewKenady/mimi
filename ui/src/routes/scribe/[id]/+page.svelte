<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { app } from '$lib/app.svelte';
	import { del, get, patch } from '$lib/api';
	import { ArrowLeft, Sparkles, Download, Trash2, Loader, CircleCheck, ListChecks, Lightbulb, FileText } from '@lucide/svelte';

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
	async function remove() {
		await del(`/api/scribe/${note.id}`);
		app.toast('Note deleted');
		goto('/scribe');
	}
	function ask() {
		app.ask(`Using my Scribe note “${note.title}”, what were the main decisions and next steps?`);
		goto('/chat');
	}
</script>

<svelte:head><title>{note?.title || 'Note'} · MIMI</title></svelte:head>

<div class="page">
	<div class="page-inner narrow">
		<a href="/scribe" class="back"><ArrowLeft size={16} /> Scribe</a>
		{#if !note}
			<div class="shimmer" style="height:40px;width:60%;margin-top:12px"></div>
		{:else}
			<header>
				{#if editingTitle}
					<input class="input titlein" bind:value={title} onblur={saveTitle} onkeydown={(e) => e.key === 'Enter' && saveTitle()} />
				{:else}
					<button class="tt" onclick={() => (editingTitle = true)} title="Rename"><h1 class="page-title">{note.title}</h1></button>
				{/if}
				<p class="page-sub">{new Date(note.created_at * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}{#if note.duration} · {fmt(note.duration)}{/if}</p>
				<div class="acts">
					{#if note.status === 'ready'}
						<button class="btn btn-sm btn-primary" onclick={ask}><Sparkles size={14} /> Ask MIMI</button>
						<a class="btn btn-sm" href="/api/scribe/{note.id}/export" download><Download size={14} /> Export</a>
					{/if}
					<button class="btn btn-sm btn-ghost" onclick={remove}><Trash2 size={14} /> Delete</button>
				</div>
			</header>

			{#if note.audio_url}
				<audio bind:this={audio} src={note.audio_url} controls preload="metadata" ontimeupdate={() => (current = audio?.currentTime || 0)}></audio>
			{/if}

			{#if note.status !== 'ready' && note.status !== 'error'}
				<div class="working card">
					<Loader size={18} class="spin" />
					<span>{note.status === 'summarizing' ? 'Writing the summary…' : note.status === 'queued' ? 'Waiting to start…' : 'Transcribing on-device…'}</span>
					<span class="prog"><span style="width:{Math.max(4, (note.progress || 0) * 100)}%"></span></span>
				</div>
			{:else if note.status === 'error'}
				<div class="working card err">{note.error}</div>
			{/if}

			{#if note.summary}
				<section class="sum card">
					{#if note.summary.summary}<p class="lead">{note.summary.summary}</p>{/if}
					{#if note.summary.key_points?.length}
						<h3><Lightbulb size={16} /> Key points</h3>
						<ul class="bullets">{#each note.summary.key_points as p}<li>{p}</li>{/each}</ul>
					{/if}
					{#if note.summary.action_items?.length}
						<h3><ListChecks size={16} /> Action items</h3>
						<ul class="todo">{#each note.summary.action_items as p}<li><CircleCheck size={15} /> {p}</li>{/each}</ul>
					{/if}
				</section>
			{/if}

			{#if note.transcript?.length}
				<h2 class="label" style="margin:28px 0 10px"><FileText size={13} /> Transcript</h2>
				<div class="transcript selectable">
					{#each note.transcript as s, i (i)}
						<p class:now={current >= s.start && current < s.end}>
							<button class="ts" onclick={() => seek(s.start)}>{fmt(s.start)}</button>
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
		gap: 6px;
		color: var(--text-3);
		font-size: 0.85rem;
	}
	.back:hover {
		color: var(--accent);
	}
	header {
		margin: 12px 0 18px;
	}
	.tt {
		text-align: left;
	}
	.titlein {
		font-size: 1.6rem;
		height: 3rem;
		font-weight: 600;
	}
	.acts {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
		margin-top: 14px;
	}
	audio {
		width: 100%;
		margin-bottom: 16px;
		border-radius: 14px;
	}
	.working {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 16px 18px;
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
		border-radius: 4px;
		background: var(--surface-3);
		overflow: hidden;
	}
	.prog span {
		display: block;
		height: 100%;
		background: var(--accent);
		transition: width 0.6s;
	}
	.sum {
		padding: 22px 24px;
	}
	.lead {
		font-size: 1.08rem;
		line-height: 1.6;
		margin: 0 0 8px;
	}
	.sum h3 {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 0.95rem;
		margin: 18px 0 8px;
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
		gap: 8px;
		align-items: flex-start;
		margin: 6px 0;
	}
	.todo :global(svg) {
		color: var(--text-3);
		flex: none;
		margin-top: 4px;
	}
	.label {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.transcript p {
		display: flex;
		gap: 14px;
		margin: 0;
		padding: 7px 10px;
		border-radius: 10px;
		line-height: 1.6;
	}
	.transcript p.now {
		background: var(--accent-soft);
	}
	.ts {
		font-variant-numeric: tabular-nums;
		color: var(--accent);
		font-size: 0.8rem;
		padding-top: 3px;
		flex: none;
		width: 44px;
		text-align: left;
	}
</style>
