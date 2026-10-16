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
	import { ScanText, AudioLines, Map, MessageSquarePlus, QrCode, Moon, Sun, Maximize, LogOut, MonitorDown, Search, UserCog, NotebookPen, Brain, Settings } from '@lucide/svelte';

	const light = $derived(document.documentElement.dataset.theme === 'light' || app.settings.user?.appearance?.theme === 'light');
	const tiles = $derived(
		[
			{ label: 'Talk', icon: AudioLines, run: () => (app.voice = true), primary: true },
			{ label: 'New chat', icon: MessageSquarePlus, run: () => goto('/chat') },
			{ label: 'Lens', icon: ScanText, run: () => goto('/lens') },
			{ label: 'Scribe', icon: NotebookPen, run: () => goto('/scribe'), hide: app.isGuest },
			{ label: 'Map', icon: Map, run: () => goto('/map') },
			{ label: 'Search', icon: Search, run: () => (app.palette = true) },
			{ label: 'Memory', icon: Brain, run: () => goto('/memory'), hide: app.isGuest || app.features.memory === false },
			{ label: 'Settings', icon: Settings, run: () => goto('/settings') },
			{ label: 'Share', icon: QrCode, run: () => goto('/settings/sharing'), hide: !app.isOwner },
			{ label: light ? 'Dark mode' : 'Light mode', icon: light ? Moon : Sun, run: () => app.setSetting('user', 'appearance', { theme: light ? 'dark' : 'light' }) },
			{ label: 'Full screen', icon: Maximize, run: () => toggleFullscreen(), hide: !inShell && innerWidth <= 760 },
			{ label: 'Exit to desktop', icon: MonitorDown, run: () => hostPost({ type: 'exit-to-desktop' }), hide: !inShell },
			{
				label: 'Sign out',
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
	<div class="qm sheet" use:dialog={{ label: 'Quick menu', onclose: close, initialFocus: '.tile' }} transition:fly={motion({ y: 30, duration: 'slow' })}>
		<div class="who">
			<span class="av" style="--c:{app.me?.color}; --ink:{inkOn(app.me?.color || DEFAULT_ACCENT)}" aria-hidden="true">{app.me?.name?.charAt(0).toUpperCase()}</span>
			<div>
				<b>{app.me?.name}</b>
				<small>{app.me?.role === 'owner' ? 'Owner' : app.me?.role === 'guest' ? 'Guest' : 'Member'}{app.boot?.local ? '' : ' · connected over the network'}</small>
			</div>
			{#if !app.isGuest}
				<button class="btn btn-sm btn-ghost acct" onclick={() => run({ run: () => goto('/settings/accounts') })}><UserCog size={15} aria-hidden="true" /> Account</button>
			{/if}
		</div>
		<div class="grid">
			{#each tiles as t (t.label)}
				{@const Icon = t.icon}
				<button class="tile" class:primary={t.primary} onclick={() => run(t)}>
					<Icon size={26} strokeWidth={1.7} aria-hidden="true" />
					<span>{t.label}</span>
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
