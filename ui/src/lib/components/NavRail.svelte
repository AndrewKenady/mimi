<script lang="ts">
	import { page } from '$app/state';
	import { app } from '$lib/app.svelte';
	import { House, MessagesSquare, Library, Map, AudioLines, ScanText, Brain, Settings, Menu } from '@lucide/svelte';

	const items = [
		{ href: '/', label: 'Home', icon: House, feature: null },
		{ href: '/chat', label: 'Chat', icon: MessagesSquare, feature: 'chat' },
		{ href: '/library', label: 'Library', icon: Library, feature: 'library' },
		{ href: '/map', label: 'Map', icon: Map, feature: 'map' },
		{ href: '/scribe', label: 'Scribe', icon: AudioLines, feature: 'scribe' },
		{ href: '/lens', label: 'Lens', icon: ScanText, feature: 'lens' },
		{ href: '/memory', label: 'Memory', icon: Brain, feature: 'memory' }
	];
	const shown = $derived(items.filter((i) => !i.feature || app.features[i.feature] !== false || i.feature === 'library'));
	const active = (href: string) => (href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href));
	const initial = $derived((app.me?.name || '?').trim().charAt(0).toUpperCase());
</script>

<nav class="rail" aria-label="Main">
	<a href="/" class="brand" aria-label="MIMI home">
		<span class="dot"></span>
	</a>
	<div class="items">
		{#each shown as it (it.href)}
			{@const Icon = it.icon}
			<a href={it.href} class="item" class:active={active(it.href)} aria-current={active(it.href) ? 'page' : undefined}>
				<span class="ico"><Icon size={21} strokeWidth={1.8} /></span>
				<span class="lbl">{it.label}</span>
			</a>
		{/each}
	</div>
	<div class="bottom">
		<button class="voice" onclick={() => (app.voice = true)} aria-label="Talk to MIMI" title="Talk to MIMI (X)">
			<span class="voice-orb"></span>
		</button>
		<a href="/settings" class="item" class:active={active('/settings')} aria-label="Settings">
			<span class="ico"><Settings size={21} strokeWidth={1.8} /></span>
			<span class="lbl">Settings</span>
		</a>
		<button class="avatar" style="--c:{app.me?.color || 'var(--accent)'}" onclick={() => (app.quick = true)} aria-label="Quick menu" title="Quick menu">
			{initial}
		</button>
	</div>
</nav>

<nav class="tabs glass" aria-label="Main">
	{#each shown.slice(0, 4) as it (it.href)}
		{@const Icon = it.icon}
		<a href={it.href} class:active={active(it.href)}>
			<Icon size={21} strokeWidth={1.8} />
			<span>{it.label}</span>
		</a>
	{/each}
	<button onclick={() => (app.quick = true)}>
		<Menu size={21} strokeWidth={1.8} />
		<span>More</span>
	</button>
</nav>

<style>
	.rail {
		width: 84px;
		flex: none;
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: 18px 0 16px;
		border-right: 1px solid var(--line);
		background: var(--bg-2);
		z-index: 5;
	}
	.brand {
		width: 40px;
		height: 40px;
		display: grid;
		place-items: center;
		margin-bottom: 18px;
	}
	.dot {
		width: 26px;
		height: 26px;
		border-radius: 50%;
		background: radial-gradient(circle at 36% 32%, #e7fffb 0, var(--well-a) 26%, var(--well-b) 56%, var(--well-c) 80%);
		box-shadow: 0 0 22px color-mix(in oklab, var(--well-a) 40%, transparent);
	}
	.items {
		display: flex;
		flex-direction: column;
		gap: 4px;
		flex: 1;
	}
	.item {
		width: 68px;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
		padding: 8px 0 7px;
		border-radius: 16px;
		color: var(--text-3);
		transition:
			color 0.18s,
			background 0.18s;
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
		border-radius: 999px;
		transition: background 0.2s;
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
		font-size: 0.68rem;
		font-weight: 550;
		letter-spacing: 0.01em;
	}
	.bottom {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 10px;
	}
	.voice {
		width: 52px;
		height: 52px;
		border-radius: 50%;
		display: grid;
		place-items: center;
		background: var(--surface);
		border: 1px solid var(--line-2);
		transition:
			transform 0.2s,
			box-shadow 0.2s;
	}
	.voice:hover {
		transform: scale(1.06);
		box-shadow: var(--shadow-glow);
	}
	.voice-orb {
		width: 26px;
		height: 26px;
		border-radius: 50%;
		background: radial-gradient(circle at 36% 32%, #e7fffb 0, var(--well-a) 30%, var(--well-b) 60%, transparent 76%);
		animation: pulse 3s ease-in-out infinite;
	}
	@keyframes pulse {
		50% {
			transform: scale(1.12);
			filter: brightness(1.15);
		}
	}
	.avatar {
		width: 36px;
		height: 36px;
		border-radius: 50%;
		display: grid;
		place-items: center;
		font-weight: 650;
		font-size: 0.9rem;
		color: #06131a;
		background: var(--c);
		margin-top: 2px;
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
			z-index: 30;
			justify-content: space-around;
			padding: 8px 6px calc(8px + env(safe-area-inset-bottom));
			border-top: 1px solid var(--line);
		}
		.tabs a,
		.tabs button {
			display: flex;
			flex-direction: column;
			align-items: center;
			gap: 3px;
			font-size: 0.68rem;
			color: var(--text-3);
			min-width: 56px;
		}
		.tabs .active {
			color: var(--accent);
		}
	}
</style>
