<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { app } from '$lib/app.svelte';
	import { get, timeAgo } from '$lib/api';
	import { fmtNumber, t } from '$lib/i18n/index.svelte';
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
	const greeting = $derived(hour < 5 ? 'home.greetingNight' : hour < 12 ? 'home.greetingMorning' : hour < 18 ? 'home.greetingAfternoon' : 'home.greetingEvening');
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
		app.ask(t('home.tellMeAbout', { name: p.name }));
		goto('/chat');
	}

	// One decimal, rounded as toFixed() rounds and without digit grouping, as English has always shown it.
	const dist1 = (n: number) => fmtNumber(+n.toFixed(1), { minimumFractionDigits: 1, maximumFractionDigits: 1, useGrouping: false });
	const fmtDist = (km: number) => (app.settings.device?.general?.units === 'metric' ? t('map.km', { n: dist1(km) }) : t('map.mi', { n: dist1(km * 0.621371) }));
</script>

<svelte:head><title>Mimi</title></svelte:head>

<div class="page">
	<div class="home">
		<section class="hero fade-up">
			<Well size={210} mood={wellState} />
			<h1>{t(greeting, { name: app.isGuest ? '' : (app.me?.name ?? '') })}</h1>
			<p class="lede">
				{#if articles}
					{t('home.ledeLibrary', { n: Math.round(articles / 1e6) })}
				{:else}
					{t('home.ledeEmpty')}
				{/if}
			</p>
			<div class="composer-wrap">
				<Composer onsend={send} bind:mode big placeholder={t('home.composerPlaceholder')} autofocus />
			</div>
			<div class="quick">
				<button class="qa" onclick={() => (app.voice = true)}><AudioLines size={18} /> {t('home.talk')}</button>
				<a class="qa" href="/lens"><ScanText size={18} /> {t('home.readPhoto')}</a>
				{#if !app.isGuest}<a class="qa" href="/scribe"><NotebookPen size={18} /> {t('home.recordNote')}</a>{/if}
				<a class="qa" href="/map"><Compass size={18} /> {t('home.whatsNearby')}</a>
			</div>
		</section>

		<section class="widgets">
			{#if widgets.includes('onthisday')}
				<article class="w card discover">
					<header>
						<span class="label">{t('home.discover')}</span>
						<button class="icon-btn sm" onclick={loadDiscover} aria-label={t('home.anotherArticle')}><Shuffle size={15} /></button>
					</header>
					{#if discover === null}
						<div class="shimmer" style="height:120px"></div>
					{:else if discover.none}
						<p class="faint">{t('home.libraryNotReady')}</p>
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
					<header><span class="label">{t('home.nearby')}</span><a href="/map" class="more">{t('home.map')} <ArrowRight size={14} /></a></header>
					{#if nearby === null}
						<div class="shimmer" style="height:110px"></div>
					{:else if !nearby.length}
						<div class="empty">
							<MapPin size={20} />
							<p>{app.location?.current ? t('home.nothingClose') : t('home.setLocationHint')}</p>
							{#if !app.location?.current}<a class="btn btn-sm" href="/map"><Navigation size={14} /> {t('home.setLocation')}</a>{/if}
						</div>
					{:else}
						<ul class="rows">
							{#each nearby as p (p.name + p.lat)}
								<li>
									<button onclick={() => openPlace(p)}>
										<span class="rt">{p.name}</span>
										<span class="rs">{t('map.placeKind', { kind: p.kind || 'place' })} · {fmtDist(p.distance_km)} {p.direction ? t('map.direction', { dir: p.direction }) : ''}</span>
									</button>
								</li>
							{/each}
						</ul>
					{/if}
				</article>
			{/if}

			{#if widgets.includes('continue')}
				<article class="w card">
					<header><span class="label">{t('home.continue')}</span><a href="/chat" class="more">{t('home.allChats')} <ArrowRight size={14} /></a></header>
					{#if chats === null}
						<div class="shimmer" style="height:110px"></div>
					{:else if !chats.length}
						<div class="empty"><MessagesSquare size={20} /><p>{t('home.chatsEmpty')}</p></div>
					{:else}
						<ul class="rows">
							{#each chats as c (c.id)}
								<li><a href="/chat/{c.id}"><span class="rt">{c.title || t('home.untitled')}</span><span class="rs">{timeAgo(c.updated_at)}</span></a></li>
							{/each}
						</ul>
					{/if}
				</article>
			{/if}

			{#if widgets.includes('notes') && !app.isGuest}
				<article class="w card">
					<header><span class="label">{t('home.recentNotes')}</span><a href="/scribe" class="more">Scribe <ArrowRight size={14} /></a></header>
					{#if notes === null}
						<div class="shimmer" style="height:110px"></div>
					{:else if !notes.length}
						<div class="empty"><NotebookPen size={20} /><p>{t('home.notesEmpty')}</p><a class="btn btn-sm" href="/scribe">{t('home.startRecording')}</a></div>
					{:else}
						<ul class="rows">
							{#each notes as n (n.id)}
								<li><a href="/scribe/{n.id}"><span class="rt">{n.title}</span><span class="rs">{n.status === 'ready' ? timeAgo(n.created_at) : t('home.noteStatus', { status: n.status })}</span></a></li>
							{/each}
						</ul>
					{/if}
				</article>
			{/if}
		</section>

		{#if books.length}
			<a class="libline" href="/library"><LibIcon size={15} /> {t('home.libraryLine', { collections: books.length, articles })} <ArrowRight size={14} /></a>
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
		font-weight: var(--fw-semibold);
		letter-spacing: -0.035em;
		margin: 0;
	}
	.lede {
		color: var(--text-2);
		margin: var(--space-2) 0 var(--space-5);
		font-size: var(--fs-base);
	}
	.composer-wrap {
		width: min(760px, 100%);
	}
	.quick {
		display: flex;
		flex-wrap: wrap;
		justify-content: center;
		gap: var(--space-2);
		margin-top: var(--space-4);
	}
	.qa {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		height: 40px;
		padding: 0 var(--space-4);
		border-radius: var(--radius-pill);
		font-size: var(--fs-md);
		font-weight: var(--fw-medium);
		color: var(--text-2);
		background: var(--surface);
		border: 1px solid var(--line);
		transition:
			color var(--dur-fast),
			border-color var(--dur-fast),
			background var(--dur-fast);
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
		gap: var(--space-4);
		margin-top: var(--space-10);
	}
	.w {
		padding: var(--space-4) var(--space-4) var(--space-3);
		min-height: 170px;
		animation: fade-up var(--dur-slower) var(--ease-out-soft) both;
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
		margin-bottom: var(--space-2);
		min-height: 32px;
	}
	.more {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		font-size: var(--fs-sm);
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
		padding: var(--space-2) var(--space-2);
		margin: 0 calc(var(--space-2) * -1);
		border-radius: var(--radius-md);
		transition: background var(--dur-fast);
	}
	.rows li > *:hover {
		background: var(--surface-2);
	}
	.rt {
		font-weight: var(--fw-medium);
		font-size: var(--fs-md);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.rs {
		font-size: var(--fs-xs);
		color: var(--text-3);
		text-transform: capitalize;
	}
	/* English capitalizes each word ("Hot Spring(s) · 1.2 Mi N"); Spanish and French use sentence case. */
	:global(:root:not(:lang(en))) .rs {
		text-transform: none;
	}
	:global(:root:not(:lang(en))) .rs::first-letter {
		text-transform: uppercase;
	}
	.empty {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-2);
		color: var(--text-3);
	}
	.empty p {
		margin: 0;
		font-size: var(--fs-md);
		color: var(--text-2);
	}
	.discover {
		grid-row: span 2;
	}
	.disc {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.disc img {
		width: 100%;
		max-height: 220px;
		object-fit: cover;
		border-radius: var(--radius-md);
		background: var(--surface-2);
	}
	.disc h3 {
		font-family: var(--font-serif);
		font-size: var(--fs-xl);
		font-weight: var(--fw-semibold);
		letter-spacing: -0.01em;
		margin: 0 0 var(--space-1-5);
	}
	.disc p {
		margin: 0 0 var(--space-2);
		color: var(--text-2);
		line-height: 1.55;
		font-size: var(--fs-md);
	}
	.src {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1-5);
		font-size: var(--fs-xs);
		color: var(--text-3);
	}
	.libline {
		display: flex;
		justify-content: center;
		align-items: center;
		gap: var(--space-2);
		margin-top: var(--space-6);
		color: var(--text-3);
		font-size: var(--fs-sm);
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
