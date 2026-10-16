<script lang="ts">
	let { checked = false, disabled = false, onchange, label = '' }: { checked?: boolean; disabled?: boolean; onchange: (v: boolean) => void; label?: string } = $props();
</script>

<button class="tg" class:on={checked} role="switch" aria-checked={checked} aria-label={label} {disabled} onclick={() => onchange(!checked)}>
	<span class="knob"></span>
</button>

<style>
	.tg {
		width: 50px;
		height: 30px;
		border-radius: var(--radius-pill);
		background: var(--surface-3);
		border: 1px solid var(--line-2);
		position: relative;
		transition: background var(--dur-base), border-color var(--dur-base);
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
		width: 22px;
		height: 22px;
		border-radius: var(--radius-round);
		background: var(--text);
		transition: transform var(--dur-slow) var(--ease-out-soft), background var(--dur-base);
		box-shadow: var(--shadow-1);
	}
	.tg.on .knob {
		transform: translateX(20px);
		background: var(--accent-ink);
	}
</style>
