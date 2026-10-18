<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { app } from '$lib/app.svelte';
	import { fmtBytes, get } from '$lib/api';
	import { fmtLanguage, t, type Key } from '$lib/i18n/index.svelte';
	import { Search, BookOpen, Sparkles, FolderOpen, X, Loader, FileText, TriangleAlert } from '@lucide/svelte';

	let books = $state<any[]>([]);
	/** Downloads that didn't finish: held back from the shelf, and said so (owner only). */
	let incomplete = $state<any[]>([]);
	let loading = $state(true);
	let searchEl: HTMLInputElement | undefined = $state();
	let q = $state(page.url.searchParams.get('q') || '');
	let coll = $state<string | null>(page.url.searchParams.get('collection'));
	let results = $state<any[] | null>(null);
	let searching = $state(false);
	let timer: ReturnType<typeof setTimeout>;

	// By collection id; headings name it in the interface language (Core's label for unknown ids).
	const groups = $derived.by(() => {
		const m = new Map<string, any[]>();
		for (const b of books) {
			if (coll && b.collection !== coll) continue;
			const k = b.collection;
			m.set(k, [...(m.get(k) || []), b]);
		}
		return [...m.entries()];
	});
	const collections = $derived([...new Map(books.map((b) => [b.collection, b.collection_label])).entries()]);
	// Honest totals: a document collection counts its documents, not Kiwix's "1 article".
	const total = $derived(books.filter((b) => b.kind === 'articles').reduce((n, b) => n + (b.items ?? b.articles), 0));
	const docs = $derived(books.filter((b) => b.kind === 'documents').reduce((n, b) => n + (b.items || 0), 0));
	const size = $derived(books.reduce((n, b) => n + (b.size || 0), 0));

	// A small, honest status for each card: can it be opened, can it be searched?
	const STATUS: Record<string, { label: Key; tone: string }> = {
		ok: { label: 'library.statusReady', tone: 'ok' },
		indexing: { label: 'library.statusIndexing', tone: 'busy' },
		checking: { label: 'library.statusChecking', tone: 'idle' },
		unreadable: { label: 'library.statusUnreadable', tone: 'bad' }
	};
	/** A book's language when it isn't English (one code; "mul" is TED's many languages): Spanish Wikivoyage and the English one share a title. */
	const otherLanguage = (b: any) => (b.language && !/^(eng|mul)$|,/.test(b.language) ? fmtLanguage(b.language) : '');

	function status(b: any) {
		const h = b.health || {};
		if (h.status === 'limited') return { label: t(h.readable ? 'library.statusBrowseOnly' : 'library.statusSearchOnly'), tone: 'warn' };
		const s = STATUS[h.status] || STATUS.checking;
		return { label: t(s.label), tone: s.tone };
	}
	// Messages with a styled part inside: the text either side of it.
	const askParts = $derived(t('library.askAbout').split('{q}'));
	const hintParts = $derived(t('library.incompleteHint').split('{cmd}'));

	async function load() {
		try {
			const r = await get('/api/library/books');
			books = r.books;
			incomplete = r.incomplete || [];
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		load().then(() => {
			if (q) search();
		});
		// While Mimi is still reading documents (first start), keep the cards' status current.
		const poll = setInterval(() => {
			if (books.some((b) => ['indexing', 'checking'].includes(b.health?.status))) load();
		}, 5000);
		return () => clearInterval(poll);
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
		const h = b.health || {};
		if (h.status === 'unreadable' || h.readable === false) {
			// Don't offer a blank page: say what's wrong, and point at search when that still works.
			app.toast(h.note || t('library.cantOpenBook'), 'info');
			if (h.searchable) searchEl?.focus();
			return;
		}
		if (b.kind && b.kind !== 'articles') return goto(`/library/book/${b.alias}`);
		const r = await get(`/api/library/home/${b.alias}`).catch(() => null);
		if (r?.kind && r.kind !== 'articles') return goto(`/library/book/${b.alias}`);
		goto(`/library/read/${b.alias}/${r?.path || ''}`);
	}

	function askAbout() {
		app.ask(q.trim());
		goto('/chat');
	}
</script>

<svelte:head><title>{t('library.title')} · Mimi</title></svelte:head>

<div class="page">
	<div class="page-inner">
		<header class="head">
			<div>
				<h1 class="page-title">{t('library.title')}</h1>
				<p class="page-sub">
					{#if books.length}{[
							t('library.collections', { n: books.length }),
							total || !docs ? t('library.itemCount', { n: total, noun: 'articles' }) : '',
							docs ? t('library.itemCount', { n: docs, noun: 'documents' }) : '',
							fmtBytes(size),
							t('library.offline')
						]
							.filter(Boolean)
							.join(' · ')}{:else}{t('library.subtitleEmpty')}{/if}
				</p>
			</div>
			{#if !app.isGuest}<a class="btn" href="/library/files"><FolderOpen size={16} /> {t('library.myFiles')}</a>{/if}
		</header>

		{#if incomplete.length}
			<div class="incomplete" role="status">
				<TriangleAlert size={16} aria-hidden="true" />
				<div>
					<p><b>{t('library.incompleteTitle', { n: incomplete.length })}</b>{t('library.incompleteRest', { n: incomplete.length })}</p>
					<ul>
						{#each incomplete as z (z.file)}
							<li><span class="mono">{z.file}</span> · {z.expected ? t('library.incompleteSize', { done: fmtBytes(z.size), total: fmtBytes(z.expected) }) : t('library.incompleteNotBook')}</li>
						{/each}
					</ul>
					<p class="faint">{hintParts[0]}<span class="mono">python -m mimi content add</span>{hintParts[1]}</p>
				</div>
			</div>
		{/if}

		<div class="searchbar">
			<Search size={19} />
			<input bind:this={searchEl} bind:value={q} oninput={onInput} onkeydown={(e) => e.key === 'Enter' && search()} placeholder={t('library.searchPlaceholder')} data-autofocus />
			{#if searching}<Loader size={17} class="spin" />{/if}
			{#if q}<button class="icon-btn sm" onclick={() => { q = ''; results = null; }} aria-label={t('library.clear')}><X size={16} /></button>{/if}
		</div>
		<div class="filters">
			<button class="chip" class:active={!coll} onclick={() => { coll = null; if (q) search(); }}>{t('library.all')}</button>
			{#each collections as [k, label] (k)}
				<button class="chip" class:active={coll === k} onclick={() => { coll = k; if (q) search(); }}>{t('library.collection', { id: k, label })}</button>
			{/each}
		</div>

		{#if results}
			<section class="results">
				{#if q.trim().length > 3}
					<button class="ask card card-hover" onclick={askAbout}>
						<Sparkles size={18} />
						<span>{askParts[0]}<b>{q}</b>{askParts[1]}</span>
					</button>
				{/if}
				{#each results as r (r.book + r.path + '#' + (r.page || 0))}
					<a class="result" href={r.url}>
						<span class="rbook">{#if r.page}<FileText size={12} />{/if}{r.book_title}</span>
						<span class="rtitle">{r.title}</span>
						<span class="rsnip">{r.snippet}</span>
					</a>
				{:else}
					{#if !searching}<p class="faint">{t('library.noMatches')}</p>{/if}
				{/each}
			</section>
		{:else if loading}
			<div class="grid">{#each Array(6) as _}<div class="shimmer" style="height:132px;border-radius:20px"></div>{/each}</div>
		{:else if !books.length}
			<div class="empty card">
				<BookOpen size={28} />
				<h3>{t('library.emptyTitle')}</h3>
				<p>{t('library.emptyBody')}</p>
			</div>
		{:else}
			{#each groups as [id, list] (id)}
				<h2 class="label glabel">{t('library.collection', { id, label: list[0].collection_label })}</h2>
				<div class="grid">
					{#each list as b (b.name)}
						{@const st = status(b)}
						<button class="book card card-hover" class:dim={st.tone === 'bad'} onclick={() => openBook(b)} title={b.health?.note || ''}>
							<span class="bicon">{#if b.icon}<img src={b.icon} alt="" />{:else}<BookOpen size={20} />{/if}</span>
							<span class="binfo">
								<b>{b.title}</b>
								<small>{b.summary}</small>
								<!-- One string: Svelte trims whitespace at the edge of {#if} blocks, which once ate the space before "·". -->
								<span class="bmeta">{[t('library.itemCount', { n: b.items ?? b.articles, noun: b.item_noun || 'articles' }), b.size ? fmtBytes(b.size) : '', otherLanguage(b)].filter(Boolean).join(' · ')}</span>
								<span class="bstatus {st.tone}"><i></i>{st.label}</span>
								{#if b.health?.note && st.tone !== 'ok' && st.tone !== 'idle'}<span class="bnote">{b.health.note}</span>{/if}
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
		min-width: 0;
		text-overflow: ellipsis; /* a long placeholder (Spanish, French, a phone) ends in "…", not mid-word */
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
	.book.dim {
		opacity: 0.62;
	}
	.book.dim:hover {
		opacity: 0.85;
	}
	.bstatus {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 0.72rem;
		color: var(--text-3);
		margin-top: 2px;
	}
	.bstatus i {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: var(--text-3);
		flex: none;
	}
	.bstatus.ok i {
		background: var(--ok);
	}
	.bstatus.warn {
		color: var(--warn);
	}
	.bstatus.warn i {
		background: var(--warn);
	}
	.bstatus.bad {
		color: var(--danger);
	}
	.bstatus.bad i {
		background: var(--danger);
	}
	.bstatus.busy {
		color: var(--accent);
	}
	.bstatus.busy i {
		background: var(--accent);
		animation: pulse 1.4s ease-in-out infinite;
	}
	.bstatus.idle i {
		background: transparent;
		border: 1px solid var(--text-3);
	}
	@keyframes pulse {
		50% {
			opacity: 0.25;
		}
	}
	.bnote {
		font-size: 0.75rem;
		line-height: 1.4;
		color: var(--text-2);
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
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
		display: inline-flex;
		align-items: center;
		gap: 5px;
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
	.incomplete {
		display: flex;
		gap: var(--space-3);
		align-items: flex-start;
		margin: 0 0 var(--space-5);
		padding: var(--space-3) var(--space-4);
		border-radius: var(--radius-md);
		border: 1px solid color-mix(in oklab, var(--warn) 40%, transparent);
		background: color-mix(in oklab, var(--warn) 8%, transparent);
		color: var(--text-2);
		font-size: var(--fs-sm);
	}
	.incomplete :global(svg) {
		color: var(--warn);
		flex: none;
		margin-top: 2px;
	}
	.incomplete p,
	.incomplete ul {
		margin: 0 0 var(--space-1);
	}
	.incomplete ul {
		padding-left: var(--space-4);
	}
	.incomplete .mono {
		font-family: var(--font-mono);
		color: var(--text);
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
