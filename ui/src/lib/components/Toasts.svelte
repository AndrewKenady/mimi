<script lang="ts">
	import { app } from '$lib/app.svelte';
	import { fly } from 'svelte/transition';
	import { motion } from '$lib/motion';
	import { CircleCheck, CircleAlert, Info, X } from '@lucide/svelte';
</script>

<!-- Errors are announced assertively, everything else politely. Hovering or focusing a
     toast pauses its timer, so an Undo can't slip away mid-reach. -->
<div class="toasts" data-toasts>
	<div class="sr-only" role="alert">{app.toasts.filter((t) => t.kind === 'error').at(-1)?.text ?? ''}</div>
	{#each app.toasts as t (t.id)}
		<div
			class="toast glass"
			class:ok={t.kind === 'ok'}
			class:err={t.kind === 'error'}
			role={t.kind === 'error' ? undefined : 'status'}
			onpointerenter={() => app.pauseToast(t.id)}
			onpointerleave={() => app.resumeToast(t.id)}
			onfocusin={() => app.pauseToast(t.id)}
			onfocusout={() => app.resumeToast(t.id)}
			in:fly={motion({ y: 16, duration: 'slow' })}
			out:fly={motion({ y: 8, duration: 'base' })}
		>
			<span class="ic" aria-hidden="true">{#if t.kind === 'ok'}<CircleCheck size={17} />{:else if t.kind === 'error'}<CircleAlert size={17} />{:else}<Info size={17} />{/if}</span>
			<span class="txt">{t.text}</span>
			{#if t.action}
				<button
					class="act"
					onclick={() => {
						t.action?.run();
						app.dismiss(t.id);
					}}>{t.action.label}</button
				>
			{/if}
			<button class="x hit" onclick={() => app.dismiss(t.id)} aria-label="Dismiss"><X size={15} /></button>
		</div>
	{/each}
</div>

<style>
	.toasts {
		position: fixed;
		left: 50%;
		bottom: var(--space-6);
		transform: translateX(-50%);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		z-index: var(--z-toast);
		pointer-events: none;
		width: min(560px, calc(100vw - 2 * var(--space-4)));
	}
	.toast {
		pointer-events: auto;
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-2) var(--space-2) var(--space-2) var(--space-4);
		min-height: var(--control-lg);
		border-radius: var(--radius-lg);
		border: 1px solid var(--line-2);
		box-shadow: var(--elev-3);
		font-size: var(--fs-md);
		line-height: var(--lh-md);
		color: var(--text);
	}
	.ic {
		display: grid;
		color: var(--text-2);
	}
	.toast.ok .ic {
		color: var(--ok);
	}
	.toast.err .ic {
		color: var(--danger);
	}
	.txt {
		flex: 1;
	}
	.act {
		color: var(--accent);
		font-weight: var(--fw-semibold);
		font-size: var(--fs-md);
		height: var(--control-sm);
		padding: 0 var(--space-3);
		border-radius: var(--radius-pill);
	}
	.act:hover {
		background: var(--accent-soft);
	}
	.x {
		color: var(--text-3);
		display: grid;
		place-items: center;
		width: var(--control-sm);
		height: var(--control-sm);
		border-radius: var(--radius-round);
	}
	.x:hover {
		background: var(--surface-3);
		color: var(--text);
	}
	@media (max-width: 760px) {
		.toasts {
			bottom: calc(var(--tabbar-h) + var(--space-3));
		}
	}
</style>
