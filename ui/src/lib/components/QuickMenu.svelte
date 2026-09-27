<script lang="ts">
	import { goto } from '$app/navigation';
	import { fade, fly } from 'svelte/transition';
	import { app } from '$lib/app.svelte';
	import { post } from '$lib/api';
	import { hostPost, inShell, toggleFullscreen } from '$lib/host';
	import { Mic, ScanText, AudioLines, Map, MessageSquarePlus, QrCode, Moon, Sun, Maximize, LogOut, MonitorDown, Search, UserCog } from '@lucide/svelte';

	const light = $derived(app.settings.user?.appearance?.theme === 'light');
	const tiles = $derived(
		[
			{ label: 'Talk', icon: Mic, run: () => (app.voice = true), primary: true },
			{ label: 'New chat', icon: MessageSquarePlus, run: () => goto('/chat') },
			{ label: 'Lens', icon: ScanText, run: () => goto('/lens') },
			{ label: 'Scribe', icon: AudioLines, run: () => goto('/scribe'), hide: app.isGuest },
			{ label: 'Map', icon: Map, run: () => goto('/map') },
			{ label: 'Search', icon: Search, run: () => (app.palette = true) },
			{ label: 'Share', icon: QrCode, run: () => goto('/settings/sharing'), hide: !app.isOwner },
			{ label: light ? 'Dark mode' : 'Light mode', icon: light ? Moon : Sun, run: () => app.setSetting('user', 'appearance', { theme: light ? 'dark' : 'light' }) },
			{ label: 'Full screen', icon: Maximize, run: () => toggleFullscreen() },
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

	function run(t: { run: () => void }) {
		app.quick = false;
		t.run();
	}

	$effect(() => {
		if (!app.quick) return;
		const back = (e: Event) => {
			e.preventDefault();
			app.quick = false;
		};
		addEventListener('mimi:back', back);
		setTimeout(() => (document.querySelector('.qm .tile') as HTMLElement)?.focus(), 60);
		return () => removeEventListener('mimi:back', back);
	});
</script>

{#if app.quick}
	<div class="scrim" transition:fade={{ duration: 160 }} onclick={() => (app.quick = false)} role="presentation"></div>
	<div class="qm" data-layer role="dialog" aria-label="Quick menu" transition:fly={{ y: 30, duration: 260 }}>
		<div class="who">
			<span class="av" style="--c:{app.me?.color}">{app.me?.name?.charAt(0).toUpperCase()}</span>
			<div>
				<b>{app.me?.name}</b>
				<small>{app.me?.role === 'owner' ? 'Device owner' : app.me?.role === 'guest' ? 'Guest' : 'User'} · {app.hardware?.device || 'MIMI'}</small>
			</div>
			{#if !app.isGuest}
				<button class="btn btn-sm btn-ghost acct" onclick={() => run({ run: () => goto('/settings/accounts') })}><UserCog size={15} /> Account</button>
			{/if}
		</div>
		<div class="grid">
			{#each tiles as t (t.label)}
				{@const Icon = t.icon}
				<button class="tile" class:primary={t.primary} onclick={() => run(t)}>
					<Icon size={26} strokeWidth={1.7} />
					<span>{t.label}</span>
				</button>
			{/each}
		</div>
	</div>
{/if}

<style>
	.scrim {
		position: fixed;
		inset: 0;
		background: rgba(3, 6, 10, 0.55);
		backdrop-filter: blur(6px);
		z-index: 70;
	}
	.qm {
		position: fixed;
		left: 50%;
		bottom: 6vh;
		transform: translateX(-50%);
		width: min(720px, calc(100vw - 24px));
		background: var(--surface);
		border: 1px solid var(--line-2);
		border-radius: 28px;
		box-shadow: var(--shadow-2);
		padding: 20px;
		z-index: 71;
	}
	.who {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 0 4px 16px;
	}
	.who .acct {
		margin-left: auto;
	}
	.who b {
		display: block;
	}
	.who small {
		color: var(--text-3);
	}
	.av {
		width: 42px;
		height: 42px;
		border-radius: 50%;
		display: grid;
		place-items: center;
		font-weight: 650;
		background: var(--c);
		color: #06131a;
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(118px, 1fr));
		gap: 10px;
	}
	.tile {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 10px;
		height: 104px;
		border-radius: 20px;
		background: var(--surface-2);
		border: 1px solid var(--line);
		color: var(--text-2);
		font-size: 0.86rem;
		font-weight: 550;
		transition:
			background 0.15s,
			color 0.15s,
			transform 0.12s;
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
