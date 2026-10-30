<script lang="ts">
	// A collection book: document libraries (PDFs, videos), TED talks, Project Gutenberg.
	// Their own home pages are built by JavaScript, which Mimi's reader never runs, so
	// Core reads the ZIM's data files and this page lists the items natively.
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { fmtBytes, get } from '#lib/api.js';
	import { t } from '#lib/i18n/index.svelte.js';
	import { ArrowLeft, BookOpen, FileText, Film, Music, File, Search, X, Image as ImageIcon, BookText } from '@lucide/svelte';

	const PAGE = 120;
	let info = $state<any>(null);
	let items = $state<any[]>([]);
	let total = $state(0);
	let error = $state('');
	let q = $state('');
	let loading = $state(true);
	let more = $state(false);
	let timer: ReturnType<typeof setTimeout>;

	const book = $derived(page.params.book!);
	const kind = $derived(info?.kind || 'documents');
	const h = $derived(info?.health || {});

	$effect(() => {
		const b = book;
		q = '';
		load(b, '', 0);
	});

	async function load(b: string, query: string, offset: number) {
		if (offset === 0) loading = true;
		else more = true;
		error = '';
		try {
			const params = new URLSearchParams({ offset: String(offset), limit: String(PAGE) });
			if (query.trim()) params.set('q', query.trim());
			const r = await get(`/api/library/collection/${encodeURIComponent(b)}?${params}`);
			info = r.book;
			total = r.total;
			items = offset ? [...items, ...r.items] : r.items;
		} catch (e: any) {
			error = e.message || t('library.collectionMissing');
		} finally {
			loading = false;
			more = false;
		}
	}

	function onInput() {
		clearTimeout(timer);
		timer = setTimeout(() => load(book, q, 0), 220);
	}

	const ICONS: Record<string, any> = { pdf: FileText, video: Film, audio: Music, image: ImageIcon, html: BookText, epub: BookOpen };
	const TYPE: Record<string, string> = $derived({
		pdf: 'PDF',
		video: t('library.typeVideo'),
		audio: t('library.typeAudio'),
		image: t('library.typeImage'),
		epub: 'EPUB',
		html: t('library.typePage'),
		text: t('library.typeText')
	});

	function meta(d: any): string {
		return [
			TYPE[d.kind] || (d.mime || t('library.typeFile')).split('/').pop()?.toUpperCase(),
			d.pages ? t('library.pages', { n: d.pages }) : '',
			d.size ? fmtBytes(d.size) : '',
			d.kind === 'pdf' ? t(d.indexed ? 'library.searchable' : h.indexing ? 'library.searchIndexing' : 'library.notSearchable') : ''
		]
			.filter(Boolean)
			.join(' · ');
	}
</script>

<svelte:head><title>{info?.title || t('library.title')} · Mimi</title></svelte:head>

<div class="coll">
	<header class="bar glass">
		<button class="icon-btn" onclick={() => (history.length > 1 ? history.back() : goto('/library'))} aria-label={t('library.back')}><ArrowLeft size={19} /></button>
		<a class="crumb" href="/library"><BookOpen size={15} /> {t('library.title')}</a>
	</header>

	<div class="scroll" data-scroll>
		<div class="inner">
			{#if error}
				<div class="msg"><h2>{t('library.notFoundTitle')}</h2><p>{error}</p><a class="btn" href="/library">{t('library.backToLibrary')}</a></div>
			{:else}
				<div class="top">
					<span class="bicon">{#if info?.icon}<img src={info.icon} alt="" />{:else}<BookOpen size={22} />{/if}</span>
					<div class="tinfo">
						<h1>{info?.title || ' '}</h1>
						{#if info?.summary}<p class="sum">{info.summary}</p>{/if}
						{#if info}
							<p class="sub">{[t('library.itemCount', { n: total, noun: info.item_noun }), info.size ? fmtBytes(info.size) : '', h.note || ''].filter(Boolean).join(' · ')}</p>
						{/if}
					</div>
				</div>

				{#if info && (info.items > 8 || q)}
					<div class="filter">
						<Search size={17} />
						<input bind:value={q} oninput={onInput} placeholder={t('library.filterPlaceholder', { noun: info.item_noun })} />
						{#if q}<button class="icon-btn sm" onclick={() => { q = ''; load(book, '', 0); }} aria-label={t('library.clear')}><X size={15} /></button>{/if}
					</div>
				{/if}

				{#if loading}
					<div class="list">{#each Array(6) as _}<div class="shimmer" style="height:76px;border-radius:16px"></div>{/each}</div>
				{:else if !items.length}
					<p class="faint empty">{q ? t('library.filterNoMatch') : t('library.collectionEmpty')}</p>
				{:else if kind === 'videos'}
					<div class="tiles">
						{#each items as d (d.id + d.path)}
							<a class="tile card card-hover" href={d.url}>
								<span class="thumb">
									<Film size={22} />
									{#if d.thumb}<img src={d.thumb} alt="" loading="lazy" onerror={(e) => ((e.currentTarget as HTMLElement).style.display = 'none')} />{/if}
								</span>
								<b>{d.title}</b>
								{#if d.author}<small>{d.author}</small>{/if}
							</a>
						{/each}
					</div>
				{:else}
					<div class="list">
						{#each items as d (d.id + d.path)}
							{@const Icon = ICONS[d.kind] || File}
							<a class="doc card card-hover" href={d.url}>
								<span class="dicon {d.kind}"><Icon size={20} /></span>
								<span class="dinfo">
									<b>{d.title}</b>
									{#if d.author}<span class="auth">{d.author}</span>{/if}
									{#if d.description}<small>{d.description}</small>{/if}
									{#if kind === 'documents'}<span class="dmeta">{meta(d)}</span>{/if}
								</span>
							</a>
						{/each}
					</div>
				{/if}

				{#if items.length < total && !loading}
					<button class="btn more" onclick={() => load(book, q, items.length)} disabled={more}>{more ? t('library.loading') : t('library.showMore', { n: total - items.length })}</button>
				{/if}
			{/if}
		</div>
	</div>
</div>

<style>
	.coll {
		height: 100%;
		display: flex;
		flex-direction: column;
	}
	.bar {
		display: flex;
		align-items: center;
		gap: 6px;
		height: 54px;
		padding: 0 14px;
		border-bottom: 1px solid var(--line);
		z-index: 2;
	}
	.crumb {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		font-size: 0.85rem;
		color: var(--text-2);
		padding: 0 8px;
	}
	.crumb:hover {
		color: var(--accent);
	}
	.scroll {
		flex: 1;
		overflow-y: auto;
	}
	.inner {
		width: min(920px, 100%);
		margin: 0 auto;
		padding: 28px 24px 80px;
	}
	.top {
		display: flex;
		gap: 18px;
		align-items: flex-start;
		margin-bottom: 22px;
	}
	.bicon {
		width: 60px;
		height: 60px;
		border-radius: 16px;
		display: grid;
		place-items: center;
		flex: none;
		background: var(--surface-2);
		color: var(--text-2);
		overflow: hidden;
	}
	.bicon img {
		width: 44px;
		height: 44px;
	}
	.tinfo h1 {
		margin: 0;
		font-size: 1.7rem;
		font-weight: 600;
		letter-spacing: -0.02em;
		font-family: var(--font-serif);
	}
	.sum {
		margin: 4px 0 0;
		color: var(--text-2);
		line-height: 1.5;
	}
	.sub {
		margin: 6px 0 0;
		font-size: 0.8rem;
		color: var(--text-3);
	}
	.filter {
		display: flex;
		align-items: center;
		gap: 10px;
		height: 46px;
		padding: 0 10px 0 16px;
		margin-bottom: 16px;
		border-radius: 16px;
		background: var(--surface);
		border: 1px solid var(--line-2);
		color: var(--text-3);
	}
	.filter:focus-within {
		border-color: var(--accent-line);
		box-shadow: 0 0 0 4px var(--accent-soft);
	}
	.filter input {
		flex: 1;
		min-width: 0;
		text-overflow: ellipsis;
		border: 0;
		background: none;
		color: var(--text);
		font-size: 0.98rem;
	}
	.list {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.doc {
		display: flex;
		gap: 14px;
		padding: 14px 16px;
		align-items: flex-start;
	}
	.dicon {
		width: 42px;
		height: 52px;
		border-radius: 8px;
		display: grid;
		place-items: center;
		flex: none;
		background: var(--surface-2);
		color: var(--text-2);
	}
	.dicon.pdf {
		color: var(--danger);
	}
	.dicon.video,
	.dicon.audio {
		color: var(--accent-2);
	}
	.dinfo {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}
	.dinfo b {
		font-weight: 600;
		font-size: 1rem;
		font-family: var(--font-serif);
	}
	.auth {
		font-size: 0.82rem;
		color: var(--text-2);
	}
	.dinfo small {
		color: var(--text-2);
		font-size: 0.84rem;
		line-height: 1.45;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.dmeta {
		font-size: 0.74rem;
		color: var(--text-3);
		margin-top: 3px;
	}
	.tiles {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
		gap: 12px;
	}
	.tile {
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 10px 10px 14px;
	}
	.thumb {
		position: relative;
		aspect-ratio: 16 / 9;
		border-radius: 10px;
		background: var(--surface-2);
		display: grid;
		place-items: center;
		color: var(--text-3);
		overflow: hidden;
		margin-bottom: 6px;
	}
	.thumb img {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		object-fit: cover;
	}
	.tile b {
		font-size: 0.92rem;
		font-weight: 600;
		line-height: 1.35;
	}
	.tile small {
		font-size: 0.8rem;
		color: var(--text-2);
	}
	.more {
		margin: 18px auto 0;
		display: flex;
	}
	.empty {
		padding: 40px 0;
		text-align: center;
	}
	.msg {
		text-align: center;
		padding: 80px 24px;
		color: var(--text-2);
	}
</style>
