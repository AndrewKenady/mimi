<!--
  The browser demo's banner: what this is, a short guided path, questions to try, "Skip the
  wait", and the way out to the case study and the code. It folds into a small pill. Demo
  build only (mounted by #lib/demo/install).
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import { tick } from 'svelte';
	import { app } from '#lib/app.svelte.js';
	import { i18n, t } from '#lib/i18n/index.svelte.js';
	import { ArrowRight, Check, ChevronUp, ExternalLink, Library, MessageCircle, Palette, Route } from '@lucide/svelte';
	import { R } from './core';
	import { demo } from './state.svelte';

	const CASE_STUDY = 'https://andrewkenady.github.io/mimi/case-study.html';
	const REPO = 'https://github.com/andrewkenady/mimi';
	const q = (id: string) => R.chats.find((c) => c.id === id)?.question ?? '';

	// Labels are message keys, so the tour follows the interface language. The question the first
	// step asks is the recorded one, in English (the banner says so in the visitor's language).
	const steps = [
		{ id: 'ask', label: 'demo.tourAsk', short: 'demo.tourAskShort', icon: MessageCircle, run: () => ask(q('grounded')) },
		{ id: 'library', label: 'demo.tourLibrary', short: 'demo.tourLibraryShort', icon: Library, run: () => goto('/library/book/zimgit-medicine_en') },
		{ id: 'design', label: 'demo.tourDesign', short: 'demo.tourDesignShort', icon: Palette, run: () => goto('/dev/design') }
	] as const;
	const current = $derived(steps.find((s) => !demo.done.includes(s.id)));
	const stepNo = $derived(current ? steps.indexOf(current) + 1 : steps.length);

	// Questions with a recorded answer (the first is the tour's own while that step is open).
	const tries = $derived([
		...R.chats.filter((c) => c.id !== 'grounded' || demo.done.includes('ask')).map((c) => ({ label: c.question, run: () => ask(c.question), route: false })),
		...(R.route?.status === 200
			? [{ label: `Old Faithful → ${R.route.to.name}`, run: () => goto(`/map?to=${R.route!.to.lat},${R.route!.to.lon}&name=${encodeURIComponent(R.route!.to.name)}`), route: true }]
			: [])
	]);

	// Tour progress follows what the visitor actually does, however they get there.
	$effect(() => {
		const p = demo.path;
		if (p.startsWith('/library/book/zimgit-medicine')) demo.complete('library');
		if (p === '/dev/design') demo.complete('design');
	});
	$effect(() => {
		const on = (e: Event) => {
			const t = (e as CustomEvent).detail?.turn;
			if (t === 'grounded' || t === 'flagged') demo.complete('ask');
		};
		addEventListener('mimi-demo:answered', on);
		return () => removeEventListener('mimi-demo:answered', on);
	});

	const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches || document.documentElement.dataset.motion === 'reduced';

	/** Put the question in the composer, as if typed, and send it. */
	async function ask(text: string) {
		if (demo.playing) return;
		const onChat = demo.path === '/' || demo.path.startsWith('/chat');
		const box = document.querySelector<HTMLTextAreaElement>('.composer textarea'); // not by its label, which follows the language
		if (!onChat || !box) {
			app.ask(text);
			await goto('/chat');
			return;
		}
		const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
		box.focus({ preventScroll: true });
		if (reduced()) set.call(box, text);
		else
			for (let i = 1; i <= text.length; i += 2) {
				set.call(box, text.slice(0, i));
				box.dispatchEvent(new Event('input', { bubbles: true }));
				await new Promise((r) => setTimeout(r, 14));
			}
		set.call(box, text);
		box.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
	}

	// The app gives up exactly the banner's height (see the global rule below).
	let bar: HTMLElement | undefined = $state();
	$effect(() => {
		const root = document.documentElement;
		if (!bar) {
			root.style.setProperty('--demo-h', '0px');
			return;
		}
		const ro = new ResizeObserver(() => root.style.setProperty('--demo-h', `${bar!.offsetHeight}px`));
		ro.observe(bar);
		return () => ro.disconnect();
	});

	let pill: HTMLButtonElement | undefined = $state();
	let foldBtn: HTMLButtonElement | undefined = $state();
	async function fold(on: boolean) {
		demo.setFolded(on);
		await tick();
		(on ? pill : foldBtn)?.focus();
	}
</script>

{#if demo.folded}
	<button bind:this={pill} class="pill" onclick={() => fold(false)} aria-expanded="false" aria-controls="mimi-demo-bar">
		<span class="orb" aria-hidden="true"></span>
		{t('demo.liveDemo')}
		{#if demo.playing}<span class="sr-only">{t('demo.answerPlaying')}</span>{/if}
	</button>
{:else}
	<section id="mimi-demo-bar" class="bar" bind:this={bar} aria-label={t('demo.about')}>
		<div class="top">
			<span class="orb" aria-hidden="true"></span>
			<p class="what">
				<b>{t('demo.liveDemo')}</b> {t('demo.what')} <span class="real">{t('demo.real')}</span>
			</p>
			<nav class="links" aria-label={t('demo.aboutMimi')}>
				<a href={CASE_STUDY} target="_blank" rel="noopener">{t('demo.caseStudy')}<ExternalLink size={12} aria-hidden="true" /><span class="sr-only">{t('demo.newTab')}</span></a>
				<a href={REPO} target="_blank" rel="noopener">GitHub<ExternalLink size={12} aria-hidden="true" /><span class="sr-only">{t('demo.newTab')}</span></a>
			</nav>
			<button bind:this={foldBtn} class="icon-btn sm fold" onclick={() => fold(true)} aria-expanded="true" aria-controls="mimi-demo-bar" aria-label={t('demo.fold')} title={t('demo.foldTitle')}>
				<ChevronUp size={16} aria-hidden="true" />
			</button>
		</div>
		<div class="row">
			{#if demo.playing}
				<p class="playing">
					<span class="dot" aria-hidden="true"></span>
					{#if demo.fast}{t('demo.replayFast')}{:else}<span class="long">{t('demo.replayReal')}</span><span class="short">{t('demo.replayRealShort')}</span>{/if}
				</p>
			{:else}
				<div class="scroll" role="group" aria-label={t('demo.tryMimi')}>
					{#if current}
						{@const Icon = current.icon}
						<button class="step" onclick={current.run}>
							<span class="n" aria-hidden="true">{stepNo}/{steps.length}</span>
							<Icon size={15} aria-hidden="true" />
							<span><span class="sr-only">{t('demo.stepOf', { n: stepNo, total: steps.length })}</span><span class="long">{t(current.label)}</span><span class="short">{t(current.short)}</span></span>
							<ArrowRight size={15} aria-hidden="true" />
						</button>
					{:else}
						<span class="tourdone"><Check size={15} aria-hidden="true" /> {t('demo.tourDone')}</span>
					{/if}
					<span class="or" aria-hidden="true">{t('demo.orTry')}</span>
					{#each tries as tr (tr.label)}
						<!-- the recorded questions are English: say so to screen readers too -->
						<button class="chip" onclick={tr.run} lang={tr.route || i18n.locale === 'en' ? undefined : 'en'}>
							{#if tr.route}<Route size={14} aria-hidden="true" />{/if}{tr.label}
						</button>
					{/each}
					<a class="chip mlink" href={CASE_STUDY} target="_blank" rel="noopener">{t('demo.caseStudy')}<ExternalLink size={12} aria-hidden="true" /><span class="sr-only">{t('demo.newTab')}</span></a>
					<a class="chip mlink" href={REPO} target="_blank" rel="noopener">GitHub<ExternalLink size={12} aria-hidden="true" /><span class="sr-only">{t('demo.newTab')}</span></a>
				</div>
			{/if}
			<button class="skip" class:on={demo.fast} class:nudge={demo.playing && !demo.fast} role="switch" aria-checked={demo.fast} onclick={() => demo.setFast(!demo.fast)}>
				<span class="lbl">{t('demo.skipWait')}</span>
				<span class="track" aria-hidden="true"><span class="knob"></span></span>
			</button>
		</div>
	</section>
{/if}

<style>
	/* The app's shell fills the viewport; under the banner it gives up the banner's height. */
	:global(html.mimi-demo .shell) {
		height: calc(100dvh - var(--demo-h, 0px));
	}
	:global(#mimi-demo) {
		display: contents;
	}
	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
		white-space: nowrap;
	}
	.bar {
		position: relative;
		z-index: var(--z-nav);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-4) var(--space-2-5, 10px);
		background:
			radial-gradient(600px 120px at 0% 0%, color-mix(in oklab, var(--accent) 9%, transparent), transparent 70%),
			var(--bg-2);
		border-bottom: 1px solid var(--line-2);
		color: var(--text-2);
		font-size: var(--fs-sm);
		line-height: var(--lh-sm);
	}
	.top {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-height: 28px;
	}
	.orb {
		flex: none;
		width: 12px;
		height: 12px;
		border-radius: var(--radius-round);
		background: var(--orb);
		box-shadow: 0 0 10px color-mix(in oklab, var(--well-a) 45%, transparent);
	}
	.what {
		flex: 1;
		min-width: 0;
		margin: 0;
	}
	.what b {
		color: var(--text);
		font-weight: var(--fw-semibold);
	}
	.links {
		display: flex;
		gap: var(--space-4);
		flex: none;
	}
	.links a {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		color: var(--text);
		font-weight: var(--fw-medium);
		text-decoration: underline;
		text-decoration-color: var(--line-2);
		text-underline-offset: 3px;
		transition: text-decoration-color var(--dur-fast) var(--ease-standard);
	}
	.links a:hover {
		text-decoration-color: currentColor;
	}
	.links :global(svg) {
		color: var(--text-3);
	}
	.fold {
		flex: none;
		width: 28px;
		height: 28px;
		margin-right: calc(-1 * var(--space-1));
	}
	.row {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding-left: calc(12px + var(--space-3));
	}
	.scroll {
		flex: 1;
		min-width: 0;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		overflow-x: auto;
		scrollbar-width: none;
		/* room for focus rings inside the scroller */
		padding: 3px;
		margin: -3px;
	}
	.scroll::-webkit-scrollbar {
		display: none;
	}
	.step {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		height: var(--control-sm);
		padding: 0 var(--space-3) 0 var(--space-1);
		border-radius: var(--radius-pill);
		background: var(--accent-soft);
		box-shadow: inset 0 0 0 1px var(--accent-line);
		color: var(--text);
		font-weight: var(--fw-semibold);
		white-space: nowrap;
		flex: none;
		transition:
			background var(--dur-fast) var(--ease-standard),
			transform var(--dur-fast) var(--ease-standard);
	}
	.step:hover {
		background: color-mix(in oklab, var(--accent) 24%, transparent);
	}
	.step:active {
		transform: scale(0.98);
	}
	.step :global(svg) {
		color: var(--accent);
	}
	.n {
		display: inline-grid;
		place-items: center;
		height: calc(var(--control-sm) - 8px);
		padding: 0 var(--space-2);
		border-radius: var(--radius-pill);
		background: var(--accent);
		color: var(--accent-ink);
		font-size: var(--fs-2xs);
		font-weight: var(--fw-bold);
		font-variant-numeric: tabular-nums;
		letter-spacing: 0.02em;
	}
	.tourdone {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1-5);
		color: var(--text);
		font-weight: var(--fw-medium);
		white-space: nowrap;
		flex: none;
	}
	.tourdone :global(svg) {
		color: var(--accent);
	}
	.or {
		color: var(--text-3);
		font-size: var(--fs-xs);
		white-space: nowrap;
		flex: none;
		padding: 0 var(--space-1);
	}
	.chip {
		flex: none;
	}
	.mlink {
		display: none;
	}
	.chip :global(svg) {
		color: var(--accent);
	}
	.skip {
		flex: none;
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		height: var(--control-sm);
		padding: 0 var(--space-1) 0 var(--space-3);
		border-radius: var(--radius-pill);
		color: var(--text);
		font-weight: var(--fw-medium);
		white-space: nowrap;
		border: 1px solid var(--line-2);
		background: var(--surface);
		transition:
			border-color var(--dur-base) var(--ease-standard),
			box-shadow var(--dur-base) var(--ease-standard);
	}
	.skip:hover {
		border-color: var(--accent-line);
	}
	.skip.nudge {
		border-color: var(--accent-line);
		box-shadow: 0 0 0 3px var(--accent-soft);
	}
	.track {
		position: relative;
		width: 34px;
		height: 22px;
		border-radius: var(--radius-pill);
		background: var(--surface-3);
		border: 1px solid var(--line-2);
		transition: background var(--dur-base) var(--ease-standard);
	}
	.knob {
		position: absolute;
		top: 2px;
		left: 2px;
		width: 16px;
		height: 16px;
		border-radius: var(--radius-round);
		background: var(--text-2);
		transition:
			transform var(--dur-slow) var(--ease-out),
			background var(--dur-base) var(--ease-standard);
	}
	.skip.on .track {
		background: var(--accent);
		border-color: transparent;
	}
	.skip.on .knob {
		transform: translateX(12px);
		background: var(--accent-ink);
	}
	.playing {
		flex: 1;
		min-width: 0;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		height: var(--control-sm);
		margin: 0;
		color: var(--text);
		font-weight: var(--fw-medium);
	}
	.short {
		display: none;
	}
	.dot {
		width: 6px;
		height: 6px;
		border-radius: var(--radius-round);
		background: var(--accent);
		animation: beat 1.4s var(--ease-breathe) infinite;
	}
	@keyframes beat {
		50% {
			opacity: 0.3;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.dot {
			animation: none;
		}
	}
	:global([data-motion='reduced']) .dot {
		animation: none;
	}

	.pill {
		position: fixed;
		z-index: var(--z-popover);
		top: 9px;
		left: 50%;
		transform: translateX(-50%);
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		height: 26px;
		padding: 0 var(--space-3) 0 var(--space-2);
		border-radius: var(--radius-pill);
		background: var(--glass);
		border: 1px solid var(--line-2);
		box-shadow: var(--elev-2);
		color: var(--text);
		font-size: var(--fs-xs);
		font-weight: var(--fw-semibold);
		backdrop-filter: blur(12px);
	}
	.pill .orb {
		width: 10px;
		height: 10px;
	}
	.pill:hover {
		border-color: var(--accent-line);
	}

	@media (max-width: 1100px) {
		.real {
			display: none;
		}
	}
	@media (max-width: 760px) {
		.bar {
			padding: var(--space-2) var(--space-3);
			gap: var(--space-1-5);
		}
		.top {
			align-items: flex-start;
		}
		.orb {
			margin-top: 4px;
		}
		.what {
			font-size: var(--fs-xs);
			line-height: var(--lh-xs);
		}
		.real {
			display: inline;
		}
		.links {
			display: none;
		}
		.mlink {
			display: inline-flex;
		}
		.row {
			padding-left: 0;
			gap: var(--space-2);
		}
		.skip .lbl {
			font-size: var(--fs-xs);
		}
		.playing {
			font-size: var(--fs-xs);
		}
		.long {
			display: none;
		}
		.short {
			display: inline;
		}
		/* more to the right: fade the edge so the row reads as scrollable */
		.scroll {
			mask-image: linear-gradient(to right, #000 calc(100% - 28px), transparent);
		}
		.pill {
			top: auto;
			bottom: calc(var(--tabbar-h) + var(--space-3));
			left: var(--space-3);
			transform: none;
		}
	}
</style>
