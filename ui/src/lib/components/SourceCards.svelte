<script lang="ts">
	import { ChevronLeft, ChevronRight } from '@lucide/svelte';
	import { sourceLabel } from '$lib/sources';
	import { t } from '$lib/i18n/index.svelte';

	let {
		sources,
		reading = false,
		onopen
	}: {
		sources: any[];
		/** The model is reading these right now (no answer text yet). */
		reading?: boolean;
		onopen?: (s: any) => void;
	} = $props();

	let row: HTMLDivElement | undefined = $state();
	let atStart = $state(true);
	let atEnd = $state(true);

	function measure() {
		if (!row) return;
		atStart = row.scrollLeft <= 2;
		atEnd = row.scrollLeft + row.clientWidth >= row.scrollWidth - 2;
	}
	$effect(() => {
		sources.length;
		if (!row) return;
		const ro = new ResizeObserver(measure);
		ro.observe(row);
		measure();
		return () => ro.disconnect();
	});

	function page(dir: number) {
		if (!row) return;
		const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches || document.documentElement.dataset.motion === 'reduced';
		row.scrollBy({ left: dir * row.clientWidth * 0.8, behavior: reduce ? 'auto' : 'smooth' });
	}
</script>

<section class="srcs" class:reading aria-label={t('chat.sources')}>
	<header>
		<span class="eyebrow">{reading ? t('chat.reading') : t('chat.sources')}</span>
		<span class="count">{sources.length}</span>
		<span class="grow"></span>
		{#if !(atStart && atEnd)}
			<button class="icon-btn sm nav" onclick={() => page(-1)} disabled={atStart} aria-label={t('chat.previousSources')}><ChevronLeft size={15} /></button>
			<button class="icon-btn sm nav" onclick={() => page(1)} disabled={atEnd} aria-label={t('chat.moreSources')}><ChevronRight size={15} /></button>
		{/if}
	</header>
	<div class="row" class:fl={!atStart} class:fr={!atEnd} bind:this={row} onscroll={measure}>
		{#each sources as s, i (s.n)}
			<button class="src" style="--i: {i}" onclick={() => onopen?.(s)} title={s.snippet || s.title} aria-label={t('chat.sourceCard', { n: s.n ?? '', title: s.title ?? '', label: sourceLabel(s) })}>
				<span class="thumb">
					{#if s.image}<img src={s.image} alt="" loading="lazy" />{/if}
					<span class="n" class:over={!!s.image}>{s.n}</span>
				</span>
				<span class="st">
					<b>{s.title}</b>
					<small>{sourceLabel(s)}</small>
				</span>
			</button>
		{/each}
	</div>
</section>

<style>
	.srcs {
		margin: 4px 0 12px;
	}
	header {
		display: flex;
		align-items: center;
		gap: 6px;
		height: 26px;
		margin-bottom: 4px;
	}
	.eyebrow {
		font-size: 0.7rem;
		font-weight: 650;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--text-3);
	}
	.reading .eyebrow {
		color: var(--accent);
	}
	.count {
		font-size: 0.7rem;
		font-weight: 650;
		min-width: 18px;
		height: 18px;
		padding: 0 5px;
		border-radius: 999px;
		display: inline-grid;
		place-items: center;
		background: var(--surface-2);
		color: var(--text-2);
		font-variant-numeric: tabular-nums;
	}
	.grow {
		flex: 1;
	}
	.nav:disabled {
		opacity: 0.35;
	}
	.row {
		display: flex;
		gap: 8px;
		overflow-x: auto;
		scroll-snap-type: x proximity;
		scroll-padding: 0 2px;
		scrollbar-width: none;
		padding: 2px 2px 4px;
		margin: 0 -2px;
		--fl: 0px;
		--fr: 0px;
		mask-image: linear-gradient(to right, transparent 0, #000 var(--fl), #000 calc(100% - var(--fr)), transparent 100%);
	}
	.row::-webkit-scrollbar {
		display: none;
	}
	.row.fl {
		--fl: 36px;
	}
	.row.fr {
		--fr: 48px;
	}
	.src {
		flex: 0 0 auto;
		width: min(236px, 74%);
		scroll-snap-align: start;
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 7px 12px 7px 7px;
		border-radius: 14px;
		background: var(--surface);
		border: 1px solid var(--line);
		text-align: left;
		transition:
			border-color 0.15s,
			background 0.15s;
		animation: card-in 0.36s var(--ease-out-soft) both;
		animation-delay: calc(var(--i) * 60ms);
	}
	@keyframes card-in {
		from {
			opacity: 0;
			transform: translateY(6px);
		}
	}
	.src:hover {
		border-color: var(--line-2);
		background: var(--surface-2);
	}
	.reading .src {
		border-color: var(--accent-line);
	}
	.thumb {
		position: relative;
		width: 42px;
		height: 42px;
		flex: none;
	}
	.thumb img {
		width: 100%;
		height: 100%;
		border-radius: 9px;
		object-fit: cover;
		background: var(--surface-3);
	}
	.n {
		position: absolute;
		inset: 0;
		border-radius: 9px;
		display: grid;
		place-items: center;
		background: var(--accent-soft);
		color: var(--accent);
		font-weight: 650;
		font-size: 0.95rem;
	}
	.n.over {
		inset: auto -4px -4px auto;
		width: 18px;
		height: 18px;
		border-radius: 999px;
		font-size: 0.66rem;
		background: var(--surface);
		border: 1px solid var(--accent-line);
	}
	.st {
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 1px;
	}
	.st b {
		font-size: 0.84rem;
		font-weight: 600;
		line-height: 1.25;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
		overflow-wrap: anywhere;
	}
	.st small {
		font-size: 0.74rem;
		color: var(--text-3);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	@media (prefers-reduced-motion: reduce) {
		.src {
			animation: none;
		}
	}
	:global([data-motion='reduced']) .src {
		animation: none;
	}
</style>
