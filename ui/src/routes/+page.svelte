<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { app } from '$lib/app.svelte';
	import { get, timeAgo } from '$lib/api';
	import Well from '$components/Well.svelte';
	import Composer from '$components/Composer.svelte';
	import { Mic, ScanText, AudioLines, Compass, MapPin, ArrowRight, BookOpen, MessagesSquare, Shuffle, Library as LibIcon, Navigation, NotebookPen } from '@lucide/svelte';

	let mode = $state(app.settings.user?.assistant?.default_mode || 'everyday');
	let nearby = $state<any[] | null>(null);
	let notes = $state<any[] | null>(null);
	let chats = $state<any[] | null>(null);
	let discover = $state<any>(null);
	let books = $state<any[]>([]);

	const widgets = $derived<string[]>(app.settings.user?.appearance?.home_widgets || ['nearby', 'notes', 'onthisday', 'continue']);
	const hour = app.clock.getHours();
	const greeting = $derived(hour < 5 ? 'Still up' : hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening');
	const articles = $derived(books.reduce((n, b) => n + (b.articles || 0), 0));
	const wellState = $derived(app.model?.status === 'loading' ? 'thinking' : 'idle');

	function send(text: string, attachments: any[]) {
		app.ask(text, { attachments, mode });
		goto('/chat');
	}

	async function loadDiscover() {
		discover = null;
		discover = await get('/api/library/random').catch(() => ({ none: true }));
	}

	onMount(() => {
		get('/api/chats').then((r) => (chats = r.chats.slice(0, 4))).catch(() => (chats = []));
		if (!app.isGuest) get('/api/scribe').then((r) => (notes = r.notes.slice(0, 3))).catch(() => (notes = []));
		get('/api/location/nearby?limit=4&radius=25').then((r) => (nearby = r.places)).catch(() => (nearby = []));
		get('/api/library/books').then((r) => (books = r.books)).catch(() => {});
		loadDiscover();
	});

	function openPlace(p: any) {
		if (p.wiki_path) return goto(`/library/read/wikipedia/${p.wiki_path}`);
		app.ask(`Tell me about ${p.name}`);
		goto('/chat');
	}

	const fmtDist = (km: number) => (app.settings.device?.general?.units === 'metric' ? `${km.toFixed(1)} km` : `${(km * 0.621371).toFixed(1)} mi`);
</script>

<svelte:head><title>Mimi</title></svelte:head>

<div class="page">
	<div class="home">
		<section class="hero fade-up">
			<Well size={210} mood={wellState} />
			<h1>{greeting}{app.isGuest ? '' : `, ${app.me?.name}`}.</h1>
			<p class="lede">
				{#if articles}
					{Math.round(articles / 1e6)} million pages of knowledge, plus maps and guides. All on this device.
				{:else}
					What would you like to know?
				{/if}
			</p>
			<div class="composer-wrap">
				<Composer onsend={send} bind:mode big placeholder="Ask Mimi anything…" autofocus />
			</div>
			<div class="quick">
				<button class="qa" onclick={() => (app.voice = true)}><AudioLines size={18} /> Talk</button>
				<a class="qa" href="/lens"><ScanText size={18} /> Read a photo</a>
				{#if !app.isGuest}<a class="qa" href="/scribe"><NotebookPen size={18} /> Record a note</a>{/if}
				<a class="qa" href="/map"><Compass size={18} /> What's nearby</a>
			</div>
		</section>

		<section class="widgets">
			{#if widgets.includes('onthisday')}
				<article class="w card discover">
					<header>
						<span class="label">Discover</span>
						<button class="icon-btn sm" onclick={loadDiscover} aria-label="Another article"><Shuffle size={15} /></button>
					</header>
					{#if discover === null}
						<div class="shimmer" style="height:120px"></div>
					{:else if discover.none}
						<p class="faint">Your library is still getting ready.</p>
					{:else}
						<a class="disc" href="/library/read/{discover.book}/{discover.path}">
							{#if discover.image}<img src={discover.image} alt="" loading="lazy" />{/if}
							<div>
								<h3>{discover.title}</h3>
								<p>{discover.excerpt}…</p>
								<span class="src">{#if discover.reason}<MapPin size={13} /> {discover.reason} · {discover.book_title}{:else}<BookOpen size={13} /> {discover.book_title}{/if}</span>
							</div>
						</a>
					{/if}
				</article>
			{/if}

			{#if widgets.includes('nearby')}
				<article class="w card">
					<header><span class="label">Nearby</span><a href="/map" class="more">Map <ArrowRight size={14} /></a></header>
					{#if nearby === null}
						<div class="shimmer" style="height:110px"></div>
					{:else if !nearby.length}
						<div class="empty">
							<MapPin size={20} />
							<p>{app.location?.current ? 'Nothing notable close by.' : 'Set your location to see places, parks and history around you.'}</p>
							{#if !app.location?.current}<a class="btn btn-sm" href="/map"><Navigation size={14} /> Set location</a>{/if}
						</div>
					{:else}
						<ul class="rows">
							{#each nearby as p (p.name + p.lat)}
								<li>
									<button onclick={() => openPlace(p)}>
										<span class="rt">{p.name}</span>
										<span class="rs">{p.kind || 'place'} · {fmtDist(p.distance_km)} {p.direction}</span>
									</button>
								</li>
							{/each}
						</ul>
					{/if}
				</article>
			{/if}

			{#if widgets.includes('continue')}
				<article class="w card">
					<header><span class="label">Continue</span><a href="/chat" class="more">All chats <ArrowRight size={14} /></a></header>
					{#if chats === null}
						<div class="shimmer" style="height:110px"></div>
					{:else if !chats.length}
						<div class="empty"><MessagesSquare size={20} /><p>Your conversations will show up here.</p></div>
					{:else}
						<ul class="rows">
							{#each chats as c (c.id)}
								<li><a href="/chat/{c.id}"><span class="rt">{c.title || 'Untitled'}</span><span class="rs">{timeAgo(c.updated_at)}</span></a></li>
							{/each}
						</ul>
					{/if}
				</article>
			{/if}

			{#if widgets.includes('notes') && !app.isGuest}
				<article class="w card">
					<header><span class="label">Recent notes</span><a href="/scribe" class="more">Scribe <ArrowRight size={14} /></a></header>
					{#if notes === null}
						<div class="shimmer" style="height:110px"></div>
					{:else if !notes.length}
						<div class="empty"><NotebookPen size={20} /><p>Record a meeting or a thought, and Mimi writes the summary.</p><a class="btn btn-sm" href="/scribe">Start recording</a></div>
					{:else}
						<ul class="rows">
							{#each notes as n (n.id)}
								<li><a href="/scribe/{n.id}"><span class="rt">{n.title}</span><span class="rs">{n.status === 'ready' ? timeAgo(n.created_at) : n.status + '…'}</span></a></li>
							{/each}
						</ul>
					{/if}
				</article>
			{/if}
		</section>

		{#if books.length}
			<a class="libline" href="/library"><LibIcon size={15} /> {books.length} offline collections · {articles.toLocaleString()} articles <ArrowRight size={14} /></a>
		{/if}
	</div>
</div>

<style>
	.home {
		max-width: 1080px;
		margin: 0 auto;
		padding: 3vh clamp(16px, 3vw, 40px) 60px;
	}
	.hero {
		display: flex;
		flex-direction: column;
		align-items: center;
		text-align: center;
	}
	h1 {
		font-size: clamp(2rem, 3.4vw, 2.7rem);
		font-weight: 600;
		letter-spacing: -0.035em;
		margin: 0;
	}
	.lede {
		color: var(--text-2);
		margin: 8px 0 22px;
		font-size: 1.05rem;
	}
	.composer-wrap {
		width: min(760px, 100%);
	}
	.quick {
		display: flex;
		flex-wrap: wrap;
		justify-content: center;
		gap: 8px;
		margin-top: 16px;
	}
	.qa {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		height: 40px;
		padding: 0 16px;
		border-radius: 999px;
		font-size: 0.88rem;
		font-weight: 550;
		color: var(--text-2);
		background: var(--surface);
		border: 1px solid var(--line);
		transition:
			color 0.15s,
			border-color 0.15s,
			background 0.15s;
	}
	.qa:hover {
		color: var(--text);
		border-color: var(--line-2);
		background: var(--surface-2);
	}
	.qa :global(svg) {
		color: var(--accent);
	}
	.widgets {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 16px;
		margin-top: 44px;
	}
	.w {
		padding: 16px 18px 14px;
		min-height: 170px;
		animation: fade-up 0.5s var(--ease-out-soft) both;
	}
	.w:nth-child(2) {
		animation-delay: 0.05s;
	}
	.w:nth-child(3) {
		animation-delay: 0.1s;
	}
	.w:nth-child(4) {
		animation-delay: 0.15s;
	}
	.w header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 10px;
		min-height: 32px;
	}
	.more {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 0.8rem;
		color: var(--text-3);
	}
	.more:hover {
		color: var(--accent);
	}
	.rows {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.rows li > * {
		display: flex;
		flex-direction: column;
		width: 100%;
		text-align: left;
		padding: 8px 10px;
		margin: 0 -10px;
		border-radius: 12px;
		transition: background 0.15s;
	}
	.rows li > *:hover {
		background: var(--surface-2);
	}
	.rt {
		font-weight: 550;
		font-size: 0.92rem;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.rs {
		font-size: 0.78rem;
		color: var(--text-3);
		text-transform: capitalize;
	}
	.empty {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 8px;
		color: var(--text-3);
	}
	.empty p {
		margin: 0;
		font-size: 0.9rem;
		color: var(--text-2);
	}
	.discover {
		grid-row: span 2;
	}
	.disc {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.disc img {
		width: 100%;
		max-height: 220px;
		object-fit: cover;
		border-radius: 14px;
		background: var(--surface-2);
	}
	.disc h3 {
		font-family: var(--font-serif);
		font-size: 1.35rem;
		font-weight: 600;
		letter-spacing: -0.01em;
		margin: 0 0 6px;
	}
	.disc p {
		margin: 0 0 10px;
		color: var(--text-2);
		line-height: 1.55;
		font-size: 0.92rem;
	}
	.src {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 0.78rem;
		color: var(--text-3);
	}
	.libline {
		display: flex;
		justify-content: center;
		align-items: center;
		gap: 8px;
		margin-top: 28px;
		color: var(--text-3);
		font-size: 0.84rem;
	}
	.libline:hover {
		color: var(--accent);
	}
	@media (max-width: 860px) {
		.widgets {
			grid-template-columns: 1fr;
		}
		.discover {
			grid-row: auto;
		}
	}
</style>
