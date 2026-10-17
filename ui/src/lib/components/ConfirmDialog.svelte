<!--
  The one confirmation dialog (see $lib/confirm). Cancel has focus, so pressing A or
  Enter by reflex never destroys anything, and the confirm button arms only after a
  beat for the same reason. B, Escape or tapping outside cancels.
-->
<script lang="ts">
	import { fade, scale } from 'svelte/transition';
	import { TriangleAlert, CircleHelp } from '@lucide/svelte';
	import { confirmState } from '$lib/confirm.svelte';
	import { dialog } from '$lib/dialog';
	import { motion } from '$lib/motion';
	import { app } from '$lib/app.svelte';
	import { t } from '$lib/i18n/index.svelte';

	const ARM_MS = 600;
	const c = $derived(confirmState.current);
	let armed = $state<number | null>(null);
	$effect(() => {
		const id = c?.id;
		armed = null;
		if (!id) return;
		const t = setTimeout(() => (armed = id), ARM_MS);
		return () => clearTimeout(t);
	});
	const danger = $derived(c?.tone === 'danger');
</script>

{#if c}
	<div class="scrim" style="z-index: var(--z-dialog)" transition:fade={motion({ duration: 'fast' })} onclick={() => confirmState.answer(false)} role="presentation"></div>
	{#key c.id}
		<div
			class="dlg sheet"
			use:dialog={{ role: 'alertdialog', labelledby: 'confirm-title', describedby: c.body ? 'confirm-body' : undefined, onclose: () => confirmState.answer(false), initialFocus: '[data-cancel]' }}
			transition:scale={motion({ start: 0.96, duration: 'base' })}
		>
			<span class="ic" class:danger aria-hidden="true">
				{#if danger}<TriangleAlert size={24} />{:else}<CircleHelp size={24} />{/if}
			</span>
			<h2 id="confirm-title">{c.title}</h2>
			{#if c.body}<p id="confirm-body">{c.body}</p>{/if}
			<div class="acts">
				<button class="btn btn-lg" data-cancel onclick={() => confirmState.answer(false)}>{c.cancelLabel ?? t('shell.cancel')}</button>
				<button
					class="btn btn-lg {danger ? 'btn-danger-solid' : 'btn-primary'}"
					aria-disabled={armed !== c.id}
					onclick={() => armed === c.id && confirmState.answer(true)}>{c.confirmLabel ?? t('shell.confirm')}</button
				>
			</div>
			{#if app.input === 'pad'}<p class="hint" aria-hidden="true">{t('shell.padCancel')}</p>{/if}
		</div>
	{/key}
{/if}

<style>
	.dlg {
		position: fixed;
		left: 50%;
		top: 50%;
		translate: -50% -50%;
		z-index: var(--z-dialog);
		width: min(440px, calc(100vw - 2 * var(--space-4)));
		padding: var(--space-8) var(--space-6) var(--space-6);
		text-align: center;
	}
	.ic {
		display: inline-grid;
		place-items: center;
		width: 3.25rem;
		height: 3.25rem;
		border-radius: var(--radius-lg);
		background: var(--accent-soft);
		color: var(--accent);
	}
	.ic.danger {
		background: var(--danger-soft);
		color: var(--danger);
	}
	h2 {
		margin: var(--space-3) 0 var(--space-2);
		font-size: var(--fs-xl);
		line-height: var(--lh-xl);
		font-weight: var(--fw-semibold);
	}
	p {
		margin: 0;
		color: var(--text-2);
		font-size: var(--fs-base);
		line-height: var(--lh-base);
	}
	.acts {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-3);
		margin-top: var(--space-6);
	}
	.hint {
		margin-top: var(--space-3);
		font-size: var(--fs-xs);
		color: var(--text-3);
	}
</style>
