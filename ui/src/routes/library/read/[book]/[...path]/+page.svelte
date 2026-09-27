<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { tick } from 'svelte';
	import { app } from '$lib/app.svelte';
	import { get } from '$lib/api';
	import { ArrowLeft, Sparkles, List, BookOpen, Type } from '@lucide/svelte';

	let art = $state<any>(null);
	let error = $state('');
	let tocOpen = $state(false);
	let scroller: HTMLDivElement | undefined = $state();
	let size = $state(Number(localStorage.getItem('mimi.readerSize') || '1'));

	$effect(() => {
		const book = page.params.book;
		const path = page.params.path || '';
		load(book!, path);
	});

	async function load(book: string, path: string) {
		error = '';
		art = null;
		try {
			art = await get(`/api/library/article/${encodeURIComponent(book)}/${path.split('/').map(encodeURIComponent).join('/')}`);
			await tick();
			const hash = decodeURIComponent(location.hash.slice(1));
			if (hash) document.getElementById(hash)?.scrollIntoView();
			else scroller?.scrollTo(0, 0);
		} catch (e: any) {
			error = e.message || 'Article not found';
		}
	}

	function onClick(e: MouseEvent) {
		const a = (e.target as HTMLElement).closest('a') as HTMLAnchorElement | null;
		if (!a) return;
		const href = a.getAttribute('href') || '';
		if (a.dataset.external) {
			e.preventDefault();
			app.toast("That link points to the internet. MIMI's library is offline.", 'info');
		} else if (href.startsWith('#')) {
			e.preventDefault();
			document.getElementById(decodeURIComponent(href.slice(1)))?.scrollIntoView({ behavior: 'smooth' });
		} else if (a.dataset.internal || href.startsWith('/library/')) {
			e.preventDefault();
			goto(href);
		}
	}

	function ask() {
		app.ask(`Using the library article “${art.title}” (${art.book_title}), give me the key points.`);
		goto('/chat');
	}

	function setSize(s: number) {
		size = Math.max(0.85, Math.min(1.4, s));
		localStorage.setItem('mimi.readerSize', String(size));
	}
</script>

<svelte:head><title>{art?.title || 'Library'} · MIMI</title></svelte:head>

<div class="reader">
	<header class="bar glass">
		<button class="icon-btn" onclick={() => history.back()} aria-label="Back"><ArrowLeft size={19} /></button>
		<a class="book" href="/library"><BookOpen size={15} /> {art?.book_title || 'Library'}</a>
		<span class="grow"></span>
		<button class="icon-btn" onclick={() => setSize(size - 0.08)} aria-label="Smaller text"><Type size={14} /></button>
		<button class="icon-btn" onclick={() => setSize(size + 0.08)} aria-label="Larger text"><Type size={19} /></button>
		{#if art?.toc?.length}<button class="icon-btn" onclick={() => (tocOpen = !tocOpen)} aria-label="Contents"><List size={19} /></button>{/if}
		{#if art}<button class="btn btn-sm btn-primary" onclick={ask}><Sparkles size={15} /> Ask MIMI</button>{/if}
	</header>

	<div class="scroll" bind:this={scroller} data-scroll>
		{#if error}
			<div class="msg"><h2>Not in the library</h2><p>{error}</p><a class="btn" href="/library">Back to the library</a></div>
		{:else if !art}
			<div class="article skel">
				<div class="shimmer" style="height:44px;width:60%"></div>
				{#each Array(8) as _}<div class="shimmer" style="height:16px;margin-top:14px"></div>{/each}
			</div>
		{:else}
			<div class="layout">
				{#if art.toc?.length}
					<nav class="toc" class:open={tocOpen} aria-label="Contents">
						<span class="label">Contents</span>
						{#each art.toc as t (t.id)}<a href="#{t.id}" onclick={(e) => { e.preventDefault(); tocOpen = false; document.getElementById(t.id)?.scrollIntoView({ behavior: 'smooth' }); }}>{t.title}</a>{/each}
					</nav>
				{/if}
				<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
				<article class="article selectable" style="--rs:{size}" onclick={onClick}>
					<h1 class="atitle">{art.title}</h1>
					<div class="kiwix">{@html art.html}</div>
				</article>
			</div>
		{/if}
	</div>
</div>

<style>
	.reader {
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
	.book {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		font-size: 0.85rem;
		color: var(--text-2);
		padding: 0 8px;
	}
	.book:hover {
		color: var(--accent);
	}
	.grow {
		flex: 1;
	}
	.scroll {
		flex: 1;
		overflow-y: auto;
	}
	.layout {
		display: flex;
		justify-content: center;
		gap: 40px;
		padding: 0 24px;
	}
	.toc {
		position: sticky;
		top: 24px;
		align-self: flex-start;
		width: 220px;
		max-height: calc(100vh - 160px);
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding-top: 36px;
		flex: none;
	}
	.toc .label {
		margin-bottom: 8px;
	}
	.toc a {
		font-size: 0.85rem;
		color: var(--text-2);
		padding: 5px 10px;
		border-radius: 8px;
		border-left: 2px solid var(--line);
	}
	.toc a:hover {
		color: var(--text);
		border-left-color: var(--accent);
		background: var(--surface);
	}
	.article {
		width: min(740px, 100%);
		padding: 32px 0 80px;
		font-family: var(--font-serif);
		font-size: calc(1.12rem * var(--rs, 1));
		line-height: 1.72;
		color: var(--text);
	}
	:global([data-reading='sans']) .article {
		font-family: var(--font-sans);
	}
	.atitle {
		font-size: 2.3em;
		font-weight: 600;
		letter-spacing: -0.02em;
		line-height: 1.15;
		margin: 0 0 0.6em;
	}
	.skel {
		margin: 0 auto;
	}
	.msg {
		text-align: center;
		padding: 80px 24px;
		color: var(--text-2);
	}
	.kiwix :global(h1) {
		display: none;
	}
	.kiwix :global(h2) {
		font-size: 1.45em;
		font-weight: 600;
		margin: 1.8em 0 0.5em;
		padding-bottom: 0.3em;
		border-bottom: 1px solid var(--line);
		letter-spacing: -0.01em;
	}
	.kiwix :global(h3) {
		font-size: 1.18em;
		font-weight: 600;
		margin: 1.4em 0 0.4em;
	}
	.kiwix :global(p) {
		margin: 0 0 1em;
	}
	.kiwix :global(a) {
		color: var(--accent);
		text-decoration: none;
		border-bottom: 1px solid var(--accent-line);
	}
	.kiwix :global(a[data-external]) {
		color: var(--text-2);
		border-bottom-style: dotted;
	}
	.kiwix :global(img) {
		max-width: 100%;
		height: auto;
		border-radius: 8px;
	}
	.kiwix :global(figure),
	.kiwix :global(.thumb) {
		margin: 1.2em 0;
		font-family: var(--font-sans);
		font-size: 0.8em;
		color: var(--text-2);
	}
	.kiwix :global(figcaption),
	.kiwix :global(.thumbcaption) {
		margin-top: 0.4em;
		line-height: 1.45;
	}
	.kiwix :global(table) {
		border-collapse: collapse;
		margin: 1em 0;
		font-family: var(--font-sans);
		font-size: 0.82em;
		max-width: 100%;
		display: block;
		overflow-x: auto;
	}
	.kiwix :global(th),
	.kiwix :global(td) {
		border: 1px solid var(--line);
		padding: 0.4em 0.6em;
		vertical-align: top;
		text-align: left;
	}
	.kiwix :global(th) {
		background: var(--surface);
	}
	.kiwix :global(table.infobox) {
		float: right;
		width: 300px;
		margin: 0 0 1.2em 1.6em;
		background: var(--surface);
		border-radius: 14px;
		overflow: hidden;
		display: table;
	}
	.kiwix :global(.infobox td),
	.kiwix :global(.infobox th) {
		border: 0;
		border-bottom: 1px solid var(--line);
	}
	.kiwix :global(ul),
	.kiwix :global(ol) {
		padding-left: 1.4em;
		margin: 0 0 1em;
	}
	.kiwix :global(blockquote) {
		border-left: 3px solid var(--accent-line);
		margin: 1em 0;
		padding-left: 1em;
		color: var(--text-2);
	}
	.kiwix :global(sup) {
		font-size: 0.65em;
		color: var(--text-3);
	}
	.kiwix :global(.reflist),
	.kiwix :global(.references) {
		font-size: 0.8em;
		color: var(--text-2);
	}
	.kiwix :global(video) {
		width: 100%;
		border-radius: 14px;
		background: #000;
	}
	.kiwix :global(pre),
	.kiwix :global(code) {
		font-family: var(--font-mono);
		font-size: 0.85em;
		background: var(--surface);
		border-radius: 6px;
	}
	.kiwix :global(pre) {
		padding: 0.8em 1em;
		overflow-x: auto;
	}
	@media (max-width: 1100px) {
		.toc {
			position: fixed;
			top: 100px;
			right: 16px;
			z-index: 5;
			background: var(--surface);
			border: 1px solid var(--line-2);
			border-radius: 16px;
			padding: 14px;
			box-shadow: var(--shadow-2);
			display: none;
		}
		.toc.open {
			display: flex;
		}
		.kiwix :global(table.infobox) {
			float: none;
			width: 100%;
			margin: 0 0 1.2em;
		}
	}
</style>
