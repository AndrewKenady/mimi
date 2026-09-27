<script lang="ts">
	import type { Snippet } from 'svelte';
	let { label, hint = '', stack = false, children }: { label: string; hint?: string; stack?: boolean; children: Snippet } = $props();
</script>

<div class="row" class:stack data-setting={label.toLowerCase()}>
	<div class="txt">
		<div class="l">{label}</div>
		{#if hint}<div class="h">{hint}</div>{/if}
	</div>
	<div class="ctl">{@render children()}</div>
</div>

<style>
	.row {
		display: flex;
		align-items: center;
		gap: 20px;
		padding: 14px 0;
		border-bottom: 1px solid var(--line);
	}
	.row:last-child {
		border-bottom: 0;
	}
	.row.stack {
		flex-direction: column;
		align-items: stretch;
		gap: 10px;
	}
	.txt {
		flex: 1;
		min-width: 0;
	}
	.l {
		font-weight: 550;
		font-size: 0.95rem;
	}
	.h {
		color: var(--text-3);
		font-size: 0.83rem;
		margin-top: 2px;
		line-height: 1.45;
	}
	.ctl {
		flex: none;
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.stack .ctl {
		flex: 1;
	}
</style>
