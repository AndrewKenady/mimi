<script lang="ts">
	import { app } from '#lib/app.svelte.js';
	import { fly } from 'svelte/transition';
	import { motion } from '#lib/motion.js';
	import { t } from '#lib/i18n/index.svelte.js';
	import { CircleCheck, CircleAlert, Info, X } from '@lucide/svelte';
</script>

<!-- Errors are announced assertively, everything else politely. Hovering or focusing a
     toast pauses its timer, so an Undo can't slip away mid-reach. -->
<div class="toasts" data-toasts>
	<div class="sr-only" role="alert">{app.toasts.filter((toast) => toast.kind === 'error').at(-1)?.text ?? ''}</div>
	{#each app.toasts as toast (toast.id)}
		<div
			class="toast glass"
			class:ok={toast.kind === 'ok'}
			class:err={toast.kind === 'error'}
			role={toast.kind === 'error' ? undefined : 'status'}
			onpointerenter={() => app.pauseToast(toast.id)}
			onpointerleave={() => app.resumeToast(toast.id)}
			onfocusin={() => app.pauseToast(toast.id)}
			onfocusout={() => app.resumeToast(toast.id)}
			in:fly={motion({ y: 16, duration: 'slow' })}
			out:fly={motion({ y: 8, duration: 'base' })}
		>
			<span class="ic" aria-hidden="true">{#if toast.kind === 'ok'}<CircleCheck size={17} />{:else if toast.kind === 'error'}<CircleAlert size={17} />{:else}<Info size={17} />{/if}</span>
			<span class="txt">{toast.text}</span>
			{#if toast.action}
				<button
					class="act"
					onclick={() => {
						toast.action?.run();
						app.dismiss(toast.id);
					}}>{toast.action.label}</button
				>
			{/if}
			<button class="x hit" onclick={() => app.dismiss(toast.id)} aria-label={t('shell.dismiss')}><X size={15} /></button>
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
