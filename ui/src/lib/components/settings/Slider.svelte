<script lang="ts">
	let {
		value,
		min = 0,
		max = 100,
		step = 1,
		onchange,
		left = '',
		right = '',
		fmt = null as null | ((v: number) => string)
	}: { value: number; min?: number; max?: number; step?: number; onchange: (v: number) => void; left?: string; right?: string; fmt?: null | ((v: number) => string) } = $props();
	let local = $state(0);
	$effect(() => {
		local = value;
	});
	const pct = $derived(((local - min) / (max - min)) * 100);
</script>

<div class="sl">
	{#if left}<span class="end">{left}</span>{/if}
	<input type="range" {min} {max} {step} bind:value={local} onchange={() => onchange(Number(local))} style="--p:{pct}%" />
	{#if right}<span class="end">{right}</span>{/if}
	{#if fmt}<span class="val">{fmt(local)}</span>{/if}
</div>

<style>
	.sl {
		display: flex;
		align-items: center;
		gap: 10px;
		min-width: 280px;
	}
	.end {
		font-size: 0.78rem;
		color: var(--text-3);
		white-space: nowrap;
	}
	.val {
		font-size: 0.82rem;
		color: var(--text-2);
		font-variant-numeric: tabular-nums;
		min-width: 3.2em;
		text-align: right;
	}
	input {
		-webkit-appearance: none;
		appearance: none;
		flex: 1;
		height: 6px;
		border-radius: 6px;
		background: linear-gradient(90deg, var(--accent) var(--p), var(--surface-3) var(--p));
		outline: none;
	}
	input::-webkit-slider-thumb {
		-webkit-appearance: none;
		width: 22px;
		height: 22px;
		border-radius: 50%;
		background: var(--text);
		border: 3px solid var(--bg);
		box-shadow: 0 0 0 1px var(--line-2), var(--shadow-1);
		cursor: pointer;
	}
</style>
