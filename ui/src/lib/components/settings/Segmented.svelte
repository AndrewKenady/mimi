<!--
  Segmented control = a radio group. One stop in the Tab order (the selected option);
  arrow keys, Home and End move and select, as for native radios. The gamepad still
  reaches every option spatially (it moves focus between buttons, A selects).
  Name it with `label`, or put it in a settings Row, which names it automatically.
-->
<script lang="ts">
	let {
		value,
		options,
		onchange,
		disabled = false,
		label = ''
	}: { value: string; options: [string, string][]; onchange: (v: string) => void; disabled?: boolean; label?: string } = $props();

	let group: HTMLElement | undefined = $state();
	const current = $derived(Math.max(0, options.findIndex(([v]) => v === value)));

	function onkey(e: KeyboardEvent, i: number) {
		const n = options.length;
		const to = { ArrowRight: i + 1, ArrowDown: i + 1, ArrowLeft: i - 1, ArrowUp: i - 1, Home: 0, End: n - 1 }[e.key];
		if (to === undefined || disabled) return;
		e.preventDefault();
		const j = (to + n) % n;
		onchange(options[j][0]);
		group?.querySelectorAll<HTMLElement>('[role=radio]')[j]?.focus();
	}
</script>

<div class="seg" role="radiogroup" aria-label={label || undefined} aria-disabled={disabled || undefined} bind:this={group}>
	{#each options as [v, text], i (v)}
		<button role="radio" aria-checked={value === v} tabindex={i === current ? 0 : -1} class:on={value === v} {disabled} onclick={() => onchange(v)} onkeydown={(e) => onkey(e, i)}
			>{text}</button
		>
	{/each}
</div>

<style>
	.seg {
		display: inline-flex;
		padding: var(--space-1);
		border-radius: var(--radius-pill);
		background: var(--surface-2);
		border: 1px solid var(--line);
		flex-wrap: wrap;
	}
	button {
		height: var(--control-sm);
		padding: 0 var(--space-3);
		border-radius: var(--radius-pill);
		font-size: var(--fs-md);
		font-weight: var(--fw-medium);
		color: var(--text-2);
		transition:
			background var(--dur-base) var(--ease-standard),
			color var(--dur-base) var(--ease-standard);
	}
	button:hover {
		color: var(--text);
	}
	button.on {
		background: var(--surface);
		color: var(--text);
		box-shadow:
			inset 0 0 0 1px var(--line-2),
			var(--elev-1);
	}
	button:disabled {
		opacity: 0.5;
	}
	@media (pointer: coarse) {
		button {
			min-height: var(--hit-min);
		}
	}
	/* Phones: options may wrap onto two rows; a pill can't hold that gracefully, so the
	   track becomes a rounded panel and options share each row evenly. */
	@media (max-width: 560px) {
		.seg {
			display: grid;
			grid-template-columns: repeat(auto-fit, minmax(7rem, 1fr));
			width: 100%;
			border-radius: var(--radius-lg);
		}
	}
</style>
