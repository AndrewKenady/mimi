<!--
  Range slider. The input itself is control-height tall, so the whole strip is the hit
  area (not just a 6px track). Its spoken value is the formatted one ("1.25×"), or,
  for unitless scales, the position between the two end labels.
-->
<script lang="ts">
	import { fmtNumber, t } from '$lib/i18n/index.svelte';
	let {
		value,
		min = 0,
		max = 100,
		step = 1,
		onchange,
		left = '',
		right = '',
		label = '',
		fmt = null as null | ((v: number) => string)
	}: {
		value: number;
		min?: number;
		max?: number;
		step?: number;
		onchange: (v: number) => void;
		left?: string;
		right?: string;
		label?: string;
		fmt?: null | ((v: number) => string);
	} = $props();
	let local = $state(0);
	$effect(() => {
		local = value;
	});
	const pct = $derived(((local - min) / (max - min)) * 100);
	const valuetext = $derived(
		fmt ? fmt(local) : left && right ? t('settings.sliderPosition', { pct: fmtNumber(Math.round(pct) / 100, { style: 'percent' }), left, right }) : fmtNumber(local)
	);
</script>

<div class="sl">
	{#if left}<span class="end" aria-hidden="true">{left}</span>{/if}
	<input type="range" {min} {max} {step} bind:value={local} onchange={() => onchange(Number(local))} style="--p:{pct}%" aria-label={label || undefined} aria-valuetext={valuetext} />
	{#if right}<span class="end" aria-hidden="true">{right}</span>{/if}
	{#if fmt}<span class="val" aria-hidden="true">{fmt(local)}</span>{/if}
</div>

<style>
	.sl {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-width: min(280px, 100%);
	}
	.end {
		font-size: var(--fs-sm);
		color: var(--text-3);
		white-space: nowrap;
	}
	.val {
		font-size: var(--fs-sm);
		color: var(--text-2);
		font-variant-numeric: tabular-nums;
		min-width: 3.2em;
		text-align: right;
	}
	input {
		-webkit-appearance: none;
		appearance: none;
		flex: 1;
		min-width: 0;
		height: var(--control-sm);
		background: transparent;
		border-radius: var(--radius-pill);
		cursor: pointer;
	}
	@media (pointer: coarse) {
		input {
			height: var(--hit-min);
		}
	}
	input::-webkit-slider-runnable-track {
		height: 6px;
		border-radius: var(--radius-pill);
		background: linear-gradient(90deg, var(--accent) var(--p), var(--surface-3) var(--p));
		box-shadow: inset 0 0 0 1px var(--line);
	}
	input::-webkit-slider-thumb {
		-webkit-appearance: none;
		width: 22px;
		height: 22px;
		margin-top: -8px;
		border-radius: var(--radius-round);
		background: var(--text);
		border: 3px solid var(--bg);
		box-shadow:
			0 0 0 1px var(--line-2),
			var(--elev-1);
	}
	input::-moz-range-track {
		height: 6px;
		border-radius: var(--radius-pill);
		background: var(--surface-3);
	}
	input::-moz-range-progress {
		height: 6px;
		border-radius: var(--radius-pill);
		background: var(--accent);
	}
	input::-moz-range-thumb {
		width: 16px;
		height: 16px;
		border-radius: var(--radius-round);
		background: var(--text);
		border: 3px solid var(--bg);
		box-shadow: 0 0 0 1px var(--line-2);
	}
</style>
