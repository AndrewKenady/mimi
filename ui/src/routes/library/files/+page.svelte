<script lang="ts">
	import { onMount } from 'svelte';
	import { app } from '#lib/app.svelte.js';
	import { del, fmtBytes, get, timeAgo, upload } from '#lib/api.js';
	import { t } from '#lib/i18n/index.svelte.js';
	import { ArrowLeft, Upload, FileText, Trash2, Loader, CircleAlert, CircleCheck, AudioLines, Search, NotebookPen } from '@lucide/svelte';

	let files = $state<any[]>([]);
	let loading = $state(true);
	let dragging = $state(false);
	let q = $state('');
	let results = $state<any[] | null>(null);
	let input: HTMLInputElement | undefined = $state();

	async function load() {
		files = (await get('/api/files').catch(() => ({ files: [] }))).files;
		loading = false;
	}
	onMount(() => {
		load();
		const h = () => load();
		addEventListener('mimi:docs', h);
		return () => removeEventListener('mimi:docs', h);
	});

	async function add(list: FileList | File[]) {
		for (const f of Array.from(list)) {
			try {
				await upload('/api/files', f);
				app.toast(t('library.addingFile', { name: f.name }), 'info');
			} catch (e: any) {
				app.toast(e.message, 'error');
			}
		}
		load();
	}
	async function remove(f: any) {
		await del(`/api/files/${f.id}`);
		load();
	}
	async function search() {
		if (!q.trim()) return (results = null);
		results = (await get(`/api/files/search?q=${encodeURIComponent(q.trim())}`)).results;
	}
</script>

<svelte:head><title>{t('library.myFiles')} · Mimi</title></svelte:head>

<div class="page">
	<div class="page-inner">
		<a href="/library" class="back"><ArrowLeft size={16} /> {t('library.title')}</a>
		<h1 class="page-title">{t('library.myFiles')}</h1>
		<p class="page-sub">{t('library.filesIntro')}</p>

		<button
			class="drop"
			class:dragging
			onclick={() => input?.click()}
			ondragover={(e) => { e.preventDefault(); dragging = true; }}
			ondragleave={() => (dragging = false)}
			ondrop={(e) => { e.preventDefault(); dragging = false; if (e.dataTransfer?.files) add(e.dataTransfer.files); }}
		>
			<Upload size={22} />
			<b>{t('library.dropFiles')}</b>
			<small>{t('library.dropHint')}</small>
		</button>
		<input bind:this={input} type="file" multiple hidden accept=".pdf,.docx,.txt,.md,.markdown,.html,.htm,.csv,.json" onchange={(e) => { const el = e.currentTarget; if (el.files) add(el.files); el.value = ''; }} />

		{#if files.length}
			<div class="search">
				<Search size={16} />
				<input placeholder={t('library.searchFiles')} bind:value={q} onkeydown={(e) => e.key === 'Enter' && search()} oninput={() => !q && (results = null)} />
			</div>
		{/if}

		{#if results}
			<div class="list">
				{#each results as r (r.chunk_id)}
					<a class="row card" href={r.url}>
						<FileText size={18} />
						<span class="info"><b>{r.title}</b><small>{r.text.slice(0, 220)}…</small></span>
					</a>
				{:else}<p class="faint">{t('library.noFileMatches')}</p>{/each}
			</div>
		{:else}
			<div class="list">
				{#each files as f (f.id)}
					<div class="row card">
						<span class="fi">{#if f.kind === 'note'}<NotebookPen size={18} />{:else}<FileText size={18} />{/if}</span>
						<span class="info">
							<b>{f.title}</b>
							<small>{f.source === 'scribe' ? t('library.scribeNote') : f.kind.toUpperCase()} · {fmtBytes(f.size)} · {timeAgo(f.created_at)}{f.chunks ? ` · ${t('library.passages', { n: f.chunks })}` : ''}</small>
						</span>
						<span class="st" class:err={f.status === 'error'}>
							{#if f.status === 'ready'}<CircleCheck size={15} /> {t('library.fileReady')}{:else if f.status === 'error'}<CircleAlert size={15} /> {f.error || t('library.fileError')}{:else}<Loader size={15} class="spin" /> {t('library.fileIndexing')}{/if}
						</span>
						<button class="icon-btn sm" onclick={() => remove(f)} aria-label={t('library.deleteFile', { title: f.title })}><Trash2 size={15} /></button>
					</div>
				{:else}
					{#if !loading}<p class="faint">{t('library.noFiles')}</p>{/if}
				{/each}
			</div>
		{/if}
	</div>
</div>

<style>
	.back {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		color: var(--text-3);
		font-size: 0.85rem;
		margin-bottom: 10px;
	}
	.back:hover {
		color: var(--accent);
	}
	.drop {
		width: 100%;
		margin: 22px 0 18px;
		padding: 30px;
		border-radius: 22px;
		border: 1.5px dashed var(--line-2);
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 6px;
		color: var(--text-2);
		background: var(--surface);
		transition: border-color 0.2s, background 0.2s;
	}
	.drop:hover,
	.drop.dragging {
		border-color: var(--accent);
		background: var(--accent-soft);
	}
	.drop small {
		color: var(--text-3);
	}
	.search {
		display: flex;
		align-items: center;
		gap: 10px;
		height: 44px;
		padding: 0 14px;
		border-radius: 14px;
		background: var(--surface);
		border: 1px solid var(--line);
		color: var(--text-3);
		margin-bottom: 12px;
	}
	.search input {
		flex: 1;
		min-width: 0;
		text-overflow: ellipsis;
		border: 0;
		background: none;
		color: var(--text);
	}
	.list {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.row {
		display: flex;
		align-items: center;
		gap: 14px;
		padding: 12px 14px;
	}
	.fi {
		width: 38px;
		height: 38px;
		border-radius: 10px;
		display: grid;
		place-items: center;
		background: var(--surface-2);
		color: var(--accent);
		flex: none;
	}
	.info {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
	}
	.info b {
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.info small {
		color: var(--text-3);
		font-size: 0.8rem;
	}
	.st {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 0.8rem;
		color: var(--ok);
	}
	.st.err {
		color: var(--danger);
	}
	.st :global(.spin) {
		animation: spin 1s linear infinite;
		color: var(--text-2);
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
</style>
