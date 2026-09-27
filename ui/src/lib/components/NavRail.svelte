<script lang="ts">
	import { page } from '$app/state';
	import { app } from '$lib/app.svelte';
	import { House, MessagesSquare, Library, Map, AudioLines, ScanText, Brain, Settings, Menu, Mic } from '@lucide/svelte';

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
	// The brand mark doubles as MIMI's presence: it breathes while a model wakes up and
	// greys out when Core can't be reached. It is the only orb in the rail.
	const presence = $derived(app.offline ? 'offline' : app.model?.status === 'loading' ? 'waking' : app.model?.status === 'error' ? 'error' : 'ok');
	const presenceLabel = $derived(
		presence === 'offline' ? 'MIMI can’t be reached' : presence === 'waking' ? `Waking up ${app.model?.model_name || 'the model'}…` : presence === 'error' ? 'The model needs attention' : `MIMI${app.model?.model_name ? ' · ' + app.model.model_name : ''}`
	);
</script>

<nav class="rail" aria-label="Main">
	<a href="/" class="brand" aria-label="MIMI home. {presenceLabel}" title={presenceLabel}>
		<span class="dot {presence}"></span>
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
		<button class="item talk" onclick={() => (app.voice = true)} title="Talk to MIMI · hold Space, or X on a controller">
			<span class="ico"><Mic size={20} strokeWidth={2} /></span>
			<span class="lbl">Talk</span>
		</button>
		<span class="sep" aria-hidden="true"></span>
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
		transition:
			filter 0.4s,
			opacity 0.4s;
	}
	.dot.waking {
		animation: breathe 1.6s ease-in-out infinite;
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
	@media (prefers-reduced-motion: reduce) {
		.dot.waking {
			animation: none;
			opacity: 0.7;
		}
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
		margin: 2px 0;
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
	/* Short screens (the handheld runs 1280x720 at 150%): tighter rhythm so nothing is cut off. */
	@media (max-height: 820px) {
		.rail {
			padding: 12px 0 10px;
			overflow-y: auto;
			scrollbar-width: none;
		}
		.brand {
			margin-bottom: 8px;
		}
		.items {
			gap: 1px;
		}
		.item {
			padding: 5px 0 4px;
			gap: 2px;
		}
		.ico {
			height: 28px;
		}
		.talk .ico {
			height: 30px;
		}
		.bottom {
			gap: 4px;
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
