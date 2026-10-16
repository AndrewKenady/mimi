<script lang="ts">
	import type { Snippet } from 'svelte';
	let { label, hint = '', stack = false, children }: { label: string; hint?: string; stack?: boolean; children?: Snippet } = $props();
</script>

<div class="row" class:stack data-setting={label.toLowerCase()}>
	<div class="txt">
		<div class="l">{label}</div>
		{#if hint}<div class="h">{hint}</div>{/if}
	</div>
	{#if children}<div class="ctl">{@render children()}</div>{/if}
</div>

<style>
	.row {
		display: flex;
		align-items: center;
		gap: var(--space-5);
		padding: var(--space-3) 0;
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
	}
	.h {
		color: var(--text-3);
		font-size: var(--fs-sm);
		margin-top: var(--space-0-5);
		line-height: 1.45;
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
</style>
