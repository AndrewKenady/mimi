<!--
  On/off switch. Inside a settings Row it is named by the row's label; pass `label`
  only when it stands alone.
-->
<script lang="ts">
	let { checked = false, disabled = false, onchange, label = '' }: { checked?: boolean; disabled?: boolean; onchange: (v: boolean) => void; label?: string } = $props();
</script>

<button class="tg hit" class:on={checked} role="switch" aria-checked={checked} aria-label={label || undefined} {disabled} onclick={() => onchange(!checked)}>
	<span class="knob"></span>
</button>

<style>
	.tg {
		width: 3.125rem;
		height: 1.875rem;
		border-radius: var(--radius-pill);
		background: var(--surface-3);
		border: 1px solid var(--line-2);
		position: relative;
		transition:
			background var(--dur-base) var(--ease-standard),
			border-color var(--dur-base) var(--ease-standard);
		flex: none;
	}
	.tg.on {
		background: var(--accent);
		border-color: transparent;
	}
	.tg:disabled {
		opacity: 0.45;
	}
	.knob {
		position: absolute;
		top: 3px;
		left: 3px;
		width: calc(1.875rem - 8px);
		height: calc(1.875rem - 8px);
		border-radius: var(--radius-round);
		background: var(--text);
		transition:
			transform var(--dur-slow) var(--ease-out),
			background var(--dur-base) var(--ease-standard);
		box-shadow: var(--elev-1);
	}
	.tg.on .knob {
		transform: translateX(calc(3.125rem - 1.875rem));
		background: var(--accent-ink);
	}
</style>
