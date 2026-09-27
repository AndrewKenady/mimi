<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { app } from '$lib/app.svelte';
	import { startGamepad } from '$lib/gamepad';
	import { toggleFullscreen } from '$lib/host';
	import NavRail from '$components/NavRail.svelte';
	import StatusStrip from '$components/StatusStrip.svelte';
	import Toasts from '$components/Toasts.svelte';
	import Onboarding from '$components/Onboarding.svelte';
	import SignIn from '$components/SignIn.svelte';
	import CommandPalette from '$components/CommandPalette.svelte';
	import QuickMenu from '$components/QuickMenu.svelte';
	import VoiceOverlay from '$components/VoiceOverlay.svelte';
	import PairRequest from '$components/PairRequest.svelte';

	let { children } = $props();

	onMount(() => {
		app.load();
		app.initHost();
		startGamepad();
		const onPointer = (e: PointerEvent) => {
			const mode = e.pointerType === 'touch' ? 'touch' : 'mouse';
			if (app.input !== mode) {
				app.input = mode;
				document.documentElement.dataset.input = mode;
			}
		};
		const onKey = (e: KeyboardEvent) => {
			if (['Tab', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key) && app.input !== 'keys') {
				app.input = 'keys';
				document.documentElement.dataset.input = 'keys';
			}
			const mod = e.ctrlKey || e.metaKey;
			if (mod && e.key.toLowerCase() === 'k') {
				e.preventDefault();
				app.palette = !app.palette;
			} else if (mod && e.shiftKey && e.key.toLowerCase() === 'v') {
				e.preventDefault();
				app.voice = !app.voice;
			} else if (e.key === 'F11') {
				e.preventDefault();
				toggleFullscreen();
			} else if (e.key === 'Escape') {
				if (app.palette) app.palette = false;
				else if (app.quick) app.quick = false;
				else if (app.voice) app.voice = false;
			}
		};
		addEventListener('pointerdown', onPointer, { passive: true });
		addEventListener('keydown', onKey);
		const mq = matchMedia('(prefers-color-scheme: light)');
		const onScheme = () => app.applyAppearance();
		mq.addEventListener('change', onScheme);
		return () => {
			removeEventListener('pointerdown', onPointer);
			removeEventListener('keydown', onKey);
			mq.removeEventListener('change', onScheme);
		};
	});
</script>

{#if app.ready}
	{#if app.boot?.needs_setup}
		<Onboarding />
	{:else if !app.me}
		<SignIn />
	{:else}
		<div class="shell">
			<NavRail />
			<div class="main">
				<StatusStrip />
				<main class="content">
					{@render children()}
				</main>
			</div>
		</div>
		<CommandPalette />
		<QuickMenu />
		{#if app.voice}<VoiceOverlay />{/if}
		<PairRequest />
	{/if}
{/if}
{#if app.offline && app.ready}
	<div class="reconnect glass">Reconnecting to MIMI Core…</div>
{/if}
<Toasts />

<style>
	.shell {
		display: flex;
		height: 100vh;
		height: 100dvh;
		background: var(--bg);
	}
	.main {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		background:
			radial-gradient(1200px 600px at 70% -10%, color-mix(in oklab, var(--accent) 5%, transparent), transparent 60%),
			var(--bg);
	}
	.content {
		flex: 1;
		min-height: 0;
		position: relative;
	}
	.reconnect {
		position: fixed;
		top: 12px;
		left: 50%;
		transform: translateX(-50%);
		padding: 8px 16px;
		border-radius: 999px;
		border: 1px solid var(--line-2);
		font-size: 0.82rem;
		color: var(--warn);
		z-index: 120;
	}
	@media (max-width: 760px) {
		.content {
			padding-bottom: 68px;
		}
	}
</style>
