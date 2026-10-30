<script lang="ts">
	import { base } from '#lib/base.js';
	import { page } from '$app/state';
	import { app } from '#lib/app.svelte.js';
	import { inkOn } from '#lib/color.js';
	import { DEFAULT_ACCENT } from '#lib/accents.js';
	import { t } from '#lib/i18n/index.svelte.js';
	import { House, MessagesSquare, Library, Map, AudioLines, ScanText, Brain, Settings, Menu, Mic, NotebookPen } from '@lucide/svelte';

	// Labels are message keys, read at render time so they follow the interface language.
	const items = [
		{ href: '/', label: 'shell.home', icon: House, feature: null },
		{ href: '/chat', label: 'shell.chat', icon: MessagesSquare, feature: 'chat' },
		{ href: '/library', label: 'shell.library', icon: Library, feature: 'library' },
		{ href: '/map', label: 'shell.map', icon: Map, feature: 'map' },
		{ href: '/scribe', label: 'shell.scribe', icon: NotebookPen, feature: 'scribe' },
		{ href: '/lens', label: 'shell.lens', icon: ScanText, feature: 'lens' },
		{ href: '/memory', label: 'shell.memory', icon: Brain, feature: 'memory' }
	] as const;
	// Rail labels over ten letters (Configuración, Bibliothèque) are set a little tighter to fit
	// the 68px item. Every English label is shorter, so English is unaffected.
	const long = (label: string) => label.length > 10;
	const shown = $derived(items.filter((i) => !i.feature || app.features[i.feature] !== false || i.feature === 'library'));
	// The browser demo is served under a base path; the app's own routes are what matter here.
	const path = $derived(__MIMI_DEMO__ ? page.url.pathname.slice(base.length) || '/' : page.url.pathname);
	const active = (href: string) => (href === '/' ? path === '/' : path.startsWith(href));
	const initial = $derived((app.me?.name || '?').trim().charAt(0).toUpperCase());
	// The brand mark doubles as Mimi's presence: it breathes while a model wakes up and
	// grays out when Core can't be reached. It is the only orb in the rail.
	const presence = $derived(app.offline ? 'offline' : app.model?.status === 'loading' ? 'waking' : app.model?.status === 'error' ? 'error' : 'ok');
	const presenceLabel = $derived(
		presence === 'offline'
			? t('shell.presenceOffline')
			: presence === 'waking'
				? app.model?.model_name
					? t('shell.presenceWaking', { name: app.model.model_name })
					: t('shell.presenceWakingModel')
				: presence === 'error'
					? t('shell.presenceError')
					: `Mimi${app.model?.model_name ? ' · ' + app.model.model_name : ''}`
	);
</script>

<nav class="rail" aria-label={t('shell.navMain')}>
	<a href="/" class="brand" aria-label={t('shell.brandLabel', { status: presenceLabel })} title={presenceLabel}>
		<span class="dot {presence}"></span>
	</a>
	<div class="items">
		{#each shown as it (it.href)}
			{@const Icon = it.icon}
			{@const label = t(it.label)}
			<a href={it.href} class="item" class:active={active(it.href)} aria-current={active(it.href) ? 'page' : undefined}>
				<span class="ico"><Icon size={21} strokeWidth={1.8} aria-hidden="true" /></span>
				<span class="lbl" class:long={long(label)}>{label}</span>
			</a>
		{/each}
	</div>
	<div class="bottom">
		<button class="item talk" onclick={() => (app.voice = true)} title={t('shell.talkTitle')}>
			<span class="ico"><AudioLines size={20} strokeWidth={2.2} /></span>
			<span class="lbl" class:long={long(t('shell.talk'))}>{t('shell.talk')}</span>
		</button>
		<span class="sep" aria-hidden="true"></span>
		<a href="/settings" class="item" class:active={active('/settings')} aria-label={t('shell.settings')}>
			<span class="ico"><Settings size={21} strokeWidth={1.8} /></span>
			<span class="lbl" class:long={long(t('shell.settings'))}>{t('shell.settings')}</span>
		</a>
		<button class="avatar" style="--c:{app.me?.color || DEFAULT_ACCENT}; --ink:{inkOn(app.me?.color || DEFAULT_ACCENT)}" onclick={() => (app.quick = true)} aria-label={t('shell.quickMenu')} aria-haspopup="dialog" title={t('shell.quickMenu')}>
			{initial}
		</button>
	</div>
</nav>

<nav class="tabs glass" aria-label={t('shell.navMain')}>
	{#each shown.slice(0, 4) as it (it.href)}
		{@const Icon = it.icon}
		<a href={it.href} class:active={active(it.href)} aria-current={active(it.href) ? 'page' : undefined}>
			<Icon size={21} strokeWidth={1.8} aria-hidden="true" />
			<span>{t(it.label)}</span>
		</a>
	{/each}
	<button onclick={() => (app.quick = true)} aria-haspopup="dialog">
		<Menu size={21} strokeWidth={1.8} aria-hidden="true" />
		<span>{t('shell.more')}</span>
	</button>
</nav>

<style>
	.rail {
		width: 84px;
		flex: none;
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: var(--space-4) 0 var(--space-4);
		border-right: 1px solid var(--line);
		background: var(--bg-2);
		z-index: var(--z-nav);
	}
	.brand {
		width: 40px;
		height: 40px;
		display: grid;
		place-items: center;
		margin-bottom: var(--space-4);
	}
	.dot {
		width: 26px;
		height: 26px;
		border-radius: var(--radius-round);
		background: var(--orb);
		box-shadow: 0 0 22px color-mix(in oklab, var(--well-a) 40%, transparent);
		transition:
			filter var(--dur-slower),
			opacity var(--dur-slower);
	}
	.dot.waking {
		animation: breathe 1.6s var(--ease-breathe) infinite;
	}
	.dot.offline {
		filter: grayscale(1) brightness(0.7);
		box-shadow: none;
	}
	.dot.error {
		filter: hue-rotate(150deg) saturate(1.3);
	}
	@keyframes breathe {
		50% {
			transform: scale(0.82);
			opacity: 0.7;
		}
	}
	/* Without motion, "waking" still reads: the mark dims instead of breathing. */
	@media (prefers-reduced-motion: reduce) {
		.dot.waking {
			animation: none;
			opacity: 0.6;
		}
	}
	:global([data-motion='reduced']) .dot.waking {
		animation: none;
		opacity: 0.6;
	}
	.items {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		flex: 1;
	}
	.item {
		width: 68px;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-1);
		padding: var(--space-2) 0 var(--space-1-5);
		border-radius: var(--radius-lg);
		color: var(--text-3);
		transition:
			color var(--dur-base),
			background var(--dur-base);
		position: relative;
	}
	.item:hover {
		color: var(--text);
		background: var(--surface);
	}
	.ico {
		display: grid;
		place-items: center;
		width: 44px;
		height: 30px;
		border-radius: var(--radius-pill);
		transition: background var(--dur-base);
	}
	.item.active {
		color: var(--text);
	}
	.item.active .ico {
		background: var(--accent-soft);
		color: var(--accent);
		box-shadow: inset 0 0 0 1px var(--accent-line);
	}
	.lbl {
		font-size: var(--fs-2xs);
		font-weight: var(--fw-medium);
		letter-spacing: 0.01em;
		/* As wide as its text, which may overhang the 68px item, centered, up to the rail's
		   width; only past that (a long translation at a large text size) does a word wrap
		   rather than run off the rail. English labels never get near it. */
		width: max-content;
		max-width: 80px;
		text-align: center;
		overflow-wrap: anywhere;
		hyphens: auto;
	}
	.lbl.long {
		font-size: 0.625rem;
		letter-spacing: 0;
	}
	.bottom {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-2);
	}
	/* Talk is an action, not a place: the one filled button in the rail. */
	.talk {
		color: var(--text-2);
	}
	.talk .ico {
		width: 44px;
		height: 32px;
		background: var(--accent);
		color: var(--accent-ink);
		box-shadow: 0 4px 14px color-mix(in oklab, var(--accent) 30%, transparent);
	}
	.talk:hover .ico {
		filter: brightness(1.08);
	}
	.talk:active .ico {
		transform: scale(0.94);
	}
	.sep {
		width: 32px;
		height: 1px;
		background: var(--line);
		margin: var(--space-0-5) 0;
	}
	.avatar {
		width: 36px;
		height: 36px;
		border-radius: var(--radius-round);
		display: grid;
		place-items: center;
		font-weight: var(--fw-bold);
		font-size: var(--fs-md);
		color: var(--ink);
		background: var(--c);
		margin-top: var(--space-0-5);
	}
	/* Short screens (the handheld runs 1280x720 at 150%): tighter rhythm so nothing is cut off. */
	@media (max-height: 820px) {
		.rail {
			padding: var(--space-3) 0 var(--space-2);
			overflow-y: auto;
			scrollbar-width: none;
		}
		.brand {
			margin-bottom: var(--space-2);
		}
		.items {
			gap: 1px;
		}
		.item {
			padding: var(--space-1) 0 var(--space-1);
			gap: var(--space-0-5);
		}
		.ico {
			height: 28px;
		}
		.talk .ico {
			height: 30px;
		}
		.bottom {
			gap: var(--space-1);
		}
	}
	.tabs {
		display: none;
	}
	@media (max-width: 760px) {
		.rail {
			display: none;
		}
		.tabs {
			display: flex;
			position: fixed;
			left: 0;
			right: 0;
			bottom: 0;
			z-index: var(--z-tabbar);
			justify-content: space-around;
			align-items: stretch;
			height: var(--tabbar-h);
			padding: var(--space-1) var(--space-1-5) env(safe-area-inset-bottom);
			border-top: 1px solid var(--line);
		}
		.tabs a,
		.tabs button {
			display: flex;
			flex-direction: column;
			align-items: center;
			justify-content: center;
			gap: var(--space-0-5);
			font-size: var(--fs-2xs);
			line-height: var(--lh-2xs);
			font-weight: var(--fw-medium);
			color: var(--text-3);
			min-width: 64px;
			border-radius: var(--radius-md);
		}
		/* On a narrow phone or at a large text size a long label wraps inside its tab
		   instead of running into the next one. */
		.tabs span {
			max-width: 100%;
			text-align: center;
			overflow-wrap: anywhere;
			hyphens: auto;
		}
		.tabs .active {
			color: var(--accent);
		}
	}
</style>
