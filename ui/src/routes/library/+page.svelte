<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { app } from '$lib/app.svelte';
	import { fmtBytes, get } from '$lib/api';
	import { Search, BookOpen, Sparkles, FolderOpen, X, Loader } from '@lucide/svelte';

	let books = $state<any[]>([]);
	let loading = $state(true);
	let q = $state(page.url.searchParams.get('q') || '');
	let coll = $state<string | null>(page.url.searchParams.get('collection'));
	let results = $state<any[] | null>(null);
	let searching = $state(false);
	let timer: ReturnType<typeof setTimeout>;

	const groups = $derived.by(() => {
		const m = new Map<string, any[]>();
		for (const b of books) {
			if (coll && b.collection !== coll) continue;
			const k = b.collection_label;
			m.set(k, [...(m.get(k) || []), b]);
		}
		return [...m.entries()];
	});
	const collections = $derived([...new Map(books.map((b) => [b.collection, b.collection_label])).entries()]);
	const total = $derived(books.reduce((n, b) => n + b.articles, 0));
	const size = $derived(books.reduce((n, b) => n + (b.size || 0), 0));

	onMount(async () => {
		try {
			books = (await get('/api/library/books')).books;
		} finally {
			loading = false;
		}
		if (q) search();
	});

	function onInput() {
		clearTimeout(timer);
		if (!q.trim()) {
			results = null;
			return;
		}
		timer = setTimeout(search, 280);
	}

	async function search() {
		if (!q.trim()) return;
		searching = true;
		try {
			const params = new URLSearchParams({ q: q.trim(), limit: '16' });
			if (coll) params.set('collection', coll);
			results = (await get(`/api/library/search?${params}`)).results;
		} catch {
			results = [];
		} finally {
			searching = false;
		}
	}

	async function openBook(b: any) {
		const r = await get(`/api/library/home/${b.alias}`).catch(() => null);
		goto(`/library/read/${b.alias}/${r?.path || ''}`);
	}

	function askAbout() {
		app.ask(q.trim());
		goto('/chat');
	}
</script>

<svelte:head><title>Library · MIMI</title></svelte:head>

<div class="page">
	<div class="page-inner">
		<header class="head">
			<div>
				<h1 class="page-title">Library</h1>
				<p class="page-sub">
					{#if books.length}{books.length} collections · {total.toLocaleString()} articles · {fmtBytes(size)} · offline{:else}Your offline reference shelf{/if}
				</p>
			</div>
			{#if !app.isGuest}<a class="btn" href="/library/files"><FolderOpen size={16} /> My files</a>{/if}
		</header>

		<div class="searchbar">
			<Search size={19} />
			<input bind:value={q} oninput={onInput} onkeydown={(e) => e.key === 'Enter' && search()} placeholder="Search every article, guide and answer…" data-autofocus />
			{#if searching}<Loader size={17} class="spin" />{/if}
			{#if q}<button class="icon-btn sm" onclick={() => { q = ''; results = null; }} aria-label="Clear"><X size={16} /></button>{/if}
		</div>
		<div class="filters">
			<button class="chip" class:active={!coll} onclick={() => { coll = null; if (q) search(); }}>All</button>
			{#each collections as [k, label] (k)}
				<button class="chip" class:active={coll === k} onclick={() => { coll = k; if (q) search(); }}>{label}</button>
			{/each}
		</div>

		{#if results}
			<section class="results">
				{#if q.trim().length > 3}
					<button class="ask card card-hover" onclick={askAbout}>
						<Sparkles size={18} />
						<span>Ask MIMI: <b>{q}</b></span>
					</button>
				{/if}
				{#each results as r (r.book + r.path)}
					<a class="result" href={r.url}>
						<span class="rbook">{r.book_title}</span>
						<span class="rtitle">{r.title}</span>
						<span class="rsnip">{r.snippet}</span>
					</a>
				{:else}
					{#if !searching}<p class="faint">No matches. Try different words.</p>{/if}
				{/each}
			</section>
		{:else if loading}
			<div class="grid">{#each Array(6) as _}<div class="shimmer" style="height:132px;border-radius:20px"></div>{/each}</div>
		{:else if !books.length}
			<div class="empty card">
				<BookOpen size={28} />
				<h3>The library is getting ready</h3>
				<p>Collections appear here as soon as they finish downloading.</p>
			</div>
		{:else}
			{#each groups as [label, list] (label)}
				<h2 class="label glabel">{label}</h2>
				<div class="grid">
					{#each list as b (b.name)}
						<button class="book card card-hover" onclick={() => openBook(b)}>
							<span class="bicon">{#if b.icon}<img src={b.icon} alt="" />{:else}<BookOpen size={20} />{/if}</span>
							<span class="binfo">
								<b>{b.title}</b>
								<small>{b.summary}</small>
								<span class="bmeta">{b.articles.toLocaleString()} {b.collection === 'talks' ? 'talks' : 'articles'}{#if b.size} · {fmtBytes(b.size)}{/if}</span>
							</span>
						</button>
					{/each}
				</div>
			{/each}
		{/if}
	</div>
</div>

<style>
	.head {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		gap: 16px;
		margin-bottom: 20px;
	}
	.searchbar {
		display: flex;
		align-items: center;
		gap: 12px;
		height: 56px;
		padding: 0 14px 0 20px;
		border-radius: 20px;
		background: var(--surface);
		border: 1px solid var(--line-2);
		color: var(--text-3);
		transition: border-color 0.2s, box-shadow 0.2s;
	}
	.searchbar:focus-within {
		border-color: var(--accent-line);
		box-shadow: 0 0 0 4px var(--accent-soft);
	}
	.searchbar input {
		flex: 1;
		border: 0;
		background: none;
		font-size: 1.05rem;
		color: var(--text);
	}
	.searchbar :global(.spin) {
		animation: spin 1s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	.filters {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
		margin: 14px 0 26px;
	}
	.glabel {
		margin: 26px 0 12px;
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
		gap: 12px;
	}
	.book {
		display: flex;
		gap: 14px;
		padding: 16px;
		text-align: left;
		align-items: flex-start;
	}
	.bicon {
		width: 48px;
		height: 48px;
		border-radius: 12px;
		display: grid;
		place-items: center;
		flex: none;
		background: var(--surface-2);
		overflow: hidden;
		color: var(--text-2);
	}
	.bicon img {
		width: 36px;
		height: 36px;
	}
	.binfo {
		display: flex;
		flex-direction: column;
		gap: 3px;
		min-width: 0;
	}
	.binfo b {
		font-weight: 600;
		font-size: 0.98rem;
	}
	.binfo small {
		color: var(--text-2);
		font-size: 0.82rem;
		line-height: 1.4;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.bmeta {
		font-size: 0.75rem;
		color: var(--text-3);
		margin-top: 4px;
	}
	.results {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.ask {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 14px 18px;
		margin-bottom: 10px;
		text-align: left;
		color: var(--text-2);
	}
	.ask :global(svg) {
		color: var(--accent);
	}
	.ask b {
		color: var(--text);
	}
	.result {
		display: flex;
		flex-direction: column;
		gap: 3px;
		padding: 14px 16px;
		border-radius: 16px;
		transition: background 0.15s;
	}
	.result:hover {
		background: var(--surface);
	}
	.rbook {
		font-size: 0.74rem;
		color: var(--accent);
		font-weight: 550;
	}
	.rtitle {
		font-size: 1.08rem;
		font-weight: 600;
		font-family: var(--font-serif);
	}
	.rsnip {
		font-size: 0.88rem;
		color: var(--text-2);
		line-height: 1.5;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 6px;
		padding: 48px;
		text-align: center;
		color: var(--text-3);
	}
	.empty h3 {
		margin: 6px 0 0;
		color: var(--text);
	}
	.empty p {
		margin: 0;
		color: var(--text-2);
	}
</style>
