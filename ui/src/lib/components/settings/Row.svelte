<!--
  A settings row: label + optional hint on the left, control on the right (or below,
  with `stack`). The visible label names the control: any form control inside without
  its own name gets aria-labelledby → the label and aria-describedby → the hint, so
  screen readers announce "Text size, slider, 100%. Used for …" with no extra wiring.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	let { label, hint = '', stack = false, children }: { label: string; hint?: string; stack?: boolean; children?: Snippet } = $props();

	const uid = $props.id();
	const labelId = `${uid}-label`;
	const hintId = `${uid}-hint`;
	const CONTROLS = 'input:not([type=hidden]), select, textarea, [role=switch], [role=radiogroup], [role=slider], [role=listbox]';

	let ctl: HTMLElement | undefined = $state();
	function wire() {
		if (!ctl) return;
		for (const el of ctl.querySelectorAll<HTMLElement>(CONTROLS)) {
			if (el.closest('[role=radiogroup]') && el.getAttribute('role') !== 'radiogroup') continue; // the group is named, not each radio
			const named = el.hasAttribute('aria-label') || el.closest('label') || (el.id && document.querySelector(`label[for="${el.id}"]`));
			if (!named || el.dataset.rowLabelled) {
				el.setAttribute('aria-labelledby', labelId);
				el.dataset.rowLabelled = '1';
			}
			if (hint) el.setAttribute('aria-describedby', hintId);
			else if (el.getAttribute('aria-describedby') === hintId) el.removeAttribute('aria-describedby');
		}
	}
	$effect(() => {
		hint;
		if (!ctl) return;
		wire();
		const mo = new MutationObserver(wire);
		mo.observe(ctl, { childList: true, subtree: true });
		return () => mo.disconnect();
	});
</script>

<div class="row" class:stack data-setting={label.toLowerCase()}>
	<div class="txt">
		<div class="l" id={labelId}>{label}</div>
		{#if hint}<div class="h" id={hintId}>{hint}</div>{/if}
	</div>
	{#if children}<div class="ctl" bind:this={ctl}>{@render children()}</div>{/if}
</div>

<style>
	.row {
		display: flex;
		align-items: center;
		gap: var(--space-5);
		padding: var(--space-3) 0;
		min-height: calc(var(--control-md) + 2 * var(--space-3));
		border-bottom: 1px solid var(--line);
	}
	.row:last-child {
		border-bottom: 0;
	}
	.row.stack {
		flex-direction: column;
		align-items: stretch;
		gap: var(--space-2);
	}
	.txt {
		flex: 1;
		min-width: 0;
	}
	.l {
		font-weight: var(--fw-medium);
		font-size: var(--fs-base);
		line-height: var(--lh-md);
	}
	.h {
		color: var(--text-3);
		font-size: var(--fs-sm);
		line-height: var(--lh-sm);
		margin-top: var(--space-0-5);
	}
	.ctl {
		flex: none;
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.stack .ctl {
		flex: 1;
	}
	@media (max-width: 560px) {
		/* Phones: wide controls drop below their label instead of squeezing it. */
		.row {
			flex-wrap: wrap;
			gap: var(--space-2) var(--space-4);
		}
		.ctl {
			flex-wrap: wrap;
			max-width: 100%;
		}
	}
</style>
