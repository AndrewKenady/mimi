<script lang="ts">
	import { goto } from '$app/navigation';
	import { fade, fly } from 'svelte/transition';
	import { app } from '$lib/app.svelte';
	import { post } from '$lib/api';
	import { hostPost, inShell, toggleFullscreen } from '$lib/host';
	import { dialog } from '$lib/dialog';
	import { motion } from '$lib/motion';
	import { inkOn } from '$lib/color';
	import { DEFAULT_ACCENT } from '$lib/accents';
	import { t } from '$lib/i18n/index.svelte';
	import { ScanText, AudioLines, Map, MessageSquarePlus, QrCode, Moon, Sun, Maximize, LogOut, MonitorDown, Search, UserCog, NotebookPen, Brain, Settings } from '@lucide/svelte';

	const light = $derived(document.documentElement.dataset.theme === 'light' || app.settings.user?.appearance?.theme === 'light');
	const tiles = $derived(
		[
			{ id: 'talk', label: t('shell.talk'), icon: AudioLines, run: () => (app.voice = true), primary: true },
			{ id: 'new', label: t('shell.newChat'), icon: MessageSquarePlus, run: () => goto('/chat') },
			{ id: 'lens', label: t('shell.lens'), icon: ScanText, run: () => goto('/lens') },
			{ id: 'scribe', label: t('shell.scribe'), icon: NotebookPen, run: () => goto('/scribe'), hide: app.isGuest },
			{ id: 'map', label: t('shell.map'), icon: Map, run: () => goto('/map') },
			{ id: 'search', label: t('shell.search'), icon: Search, run: () => (app.palette = true) },
			{ id: 'memory', label: t('shell.memory'), icon: Brain, run: () => goto('/memory'), hide: app.isGuest || app.features.memory === false },
			{ id: 'settings', label: t('shell.settings'), icon: Settings, run: () => goto('/settings') },
			{ id: 'share', label: t('shell.share'), icon: QrCode, run: () => goto('/settings/sharing'), hide: !app.isOwner },
			{ id: 'theme', label: light ? t('shell.darkMode') : t('shell.lightMode'), icon: light ? Moon : Sun, run: () => app.setSetting('user', 'appearance', { theme: light ? 'dark' : 'light' }) },
			{ id: 'fullscreen', label: t('shell.fullScreen'), icon: Maximize, run: () => toggleFullscreen(), hide: !inShell && innerWidth <= 760 },
			{ id: 'exit', label: t('shell.exitToDesktop'), icon: MonitorDown, run: () => hostPost({ type: 'exit-to-desktop' }), hide: !inShell },
			{
				id: 'signout',
				label: t('shell.signOut'),
				icon: LogOut,
				run: async () => {
					await post('/api/auth/logout');
					location.reload();
				},
				hide: !!app.boot?.local && app.isOwner
			}
		].filter((t) => !t.hide)
	);

	const close = () => (app.quick = false);
	function run(t: { run: () => void }) {
		close();
		t.run();
	}
</script>

{#if app.quick}
	<div class="scrim" style="z-index: var(--z-sheet)" transition:fade={motion({ duration: 'fast' })} onclick={close} role="presentation"></div>
	<div class="qm sheet" use:dialog={{ label: t('shell.quickMenu'), onclose: close, initialFocus: '.tile' }} transition:fly={motion({ y: 30, duration: 'slow' })}>
		<div class="who">
			<span class="av" style="--c:{app.me?.color}; --ink:{inkOn(app.me?.color || DEFAULT_ACCENT)}" aria-hidden="true">{app.me?.name?.charAt(0).toUpperCase()}</span>
			<div>
				<b>{app.me?.name}</b>
				<small>{app.me?.role === 'owner' ? t('shell.owner') : app.me?.role === 'guest' ? t('shell.guest') : t('shell.member')}{app.boot?.local ? '' : ` · ${t('shell.overNetwork')}`}</small>
			</div>
			{#if !app.isGuest}
				<button class="btn btn-sm btn-ghost acct" onclick={() => run({ run: () => goto('/settings/accounts') })}><UserCog size={15} aria-hidden="true" /> {t('shell.account')}</button>
			{/if}
		</div>
		<div class="grid">
			{#each tiles as tile (tile.id)}
				{@const Icon = tile.icon}
				<button class="tile" class:primary={tile.primary} onclick={() => run(tile)}>
					<Icon size={26} strokeWidth={1.7} aria-hidden="true" />
					<span>{tile.label}</span>
				</button>
			{/each}
		</div>
	</div>
{/if}

<style>
	.qm {
		position: fixed;
		left: 50%;
		bottom: 6vh;
		transform: translateX(-50%);
		width: min(720px, calc(100vw - 2 * var(--space-3)));
		padding: var(--space-5);
		z-index: var(--z-sheet);
		max-height: calc(100dvh - 12vh);
		overflow-y: auto;
		overscroll-behavior: contain;
	}
	@media (max-width: 760px) {
		.qm {
			bottom: calc(var(--tabbar-h) + var(--space-2));
			max-height: calc(100dvh - var(--tabbar-h) - var(--space-8));
			padding: var(--space-4);
		}
		.tile {
			height: 5.25rem !important;
		}
		/* A longer Spanish or French label can wrap to two lines on these shorter tiles: let
		   the tiles grow to fit it, every row alike. */
		.grid:not(:lang(en)) {
			grid-auto-rows: 1fr;
		}
		.grid:not(:lang(en)) .tile {
			height: auto !important;
			min-height: 5.25rem;
			padding-block: var(--space-2);
		}
	}
	.who {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: 0 var(--space-1) var(--space-4);
	}
	.who .acct {
		margin-left: auto;
	}
	.who b {
		display: block;
		font-weight: var(--fw-semibold);
	}
	.who small {
		color: var(--text-3);
		font-size: var(--fs-sm);
	}
	.av {
		flex: none; /* stays round when the line beside it is long */
		width: 2.625rem;
		height: 2.625rem;
		border-radius: var(--radius-round);
		display: grid;
		place-items: center;
		font-weight: var(--fw-bold);
		background: var(--c);
		color: var(--ink);
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(118px, 1fr));
		gap: var(--space-3);
	}
	.tile {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--space-3);
		height: 6.5rem;
		border-radius: var(--radius-xl);
		background: var(--surface-2);
		border: 1px solid var(--line);
		color: var(--text-2);
		font-size: var(--fs-md);
		font-weight: var(--fw-medium);
		transition:
			background var(--dur-fast) var(--ease-standard),
			color var(--dur-fast) var(--ease-standard),
			transform var(--dur-instant) var(--ease-standard);
	}
	/* Spanish and French labels run longer ("Pantalla completa", "Quitter vers le bureau"):
	   keep them off the tile's edges and split two lines evenly. English labels all fit on
	   one line already and keep their exact layout. */
	.tile:not(:lang(en)) {
		padding-inline: var(--space-1-5);
		text-wrap: balance;
	}
	.tile:hover,
	.tile:focus {
		background: var(--surface-3);
		color: var(--text);
	}
	.tile:active {
		transform: scale(0.97);
	}
	.tile.primary {
		background: var(--accent-soft);
		border-color: var(--accent-line);
		color: var(--accent);
	}
</style>
