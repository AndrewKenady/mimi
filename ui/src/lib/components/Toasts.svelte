<script lang="ts">
	import { app } from '$lib/app.svelte';
	import { fly } from 'svelte/transition';
	import { CircleCheck, CircleAlert, Info, X } from '@lucide/svelte';
</script>

<div class="toasts" aria-live="polite">
	{#each app.toasts as t (t.id)}
		<div class="toast glass" class:ok={t.kind === 'ok'} class:err={t.kind === 'error'} in:fly={{ y: 16, duration: 280 }} out:fly={{ y: 8, duration: 180 }}>
			{#if t.kind === 'ok'}<CircleCheck size={17} />{:else if t.kind === 'error'}<CircleAlert size={17} />{:else}<Info size={17} />{/if}
			<span class="txt">{t.text}</span>
			{#if t.action}
				<button class="act" onclick={() => { t.action?.run(); app.dismiss(t.id); }}>{t.action.label}</button>
			{/if}
			<button class="x" onclick={() => app.dismiss(t.id)} aria-label="Dismiss"><X size={15} /></button>
		</div>
	{/each}
</div>

<style>
	.toasts {
		position: fixed;
		left: 50%;
		bottom: 28px;
		transform: translateX(-50%);
		display: flex;
		flex-direction: column;
		gap: 8px;
		z-index: 100;
		pointer-events: none;
		width: min(560px, calc(100vw - 32px));
	}
	.toast {
		pointer-events: auto;
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 11px 12px 11px 16px;
		border-radius: 16px;
		border: 1px solid var(--line-2);
		box-shadow: var(--shadow-2);
		font-size: 0.9rem;
		color: var(--text);
	}
	.toast.ok :global(svg:first-child) {
		color: var(--ok);
	}
	.toast.err :global(svg:first-child) {
		color: var(--danger);
	}
	.txt {
		flex: 1;
	}
	.act {
		color: var(--accent);
		font-weight: 600;
		font-size: 0.85rem;
		padding: 4px 8px;
	}
	.x {
		color: var(--text-3);
		display: grid;
		place-items: center;
		width: 26px;
		height: 26px;
		border-radius: 50%;
	}
	.x:hover {
		background: var(--surface-3);
	}
	@media (max-width: 760px) {
		.toasts {
			bottom: 86px;
		}
	}
</style>
