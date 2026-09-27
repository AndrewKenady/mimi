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
		border-radius: 999px;
		background: var(--surface-3);
		border: 1px solid var(--line-2);
		position: relative;
		transition: background 0.2s, border-color 0.2s;
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
		border-radius: 50%;
		background: var(--text);
		transition: transform 0.25s var(--ease-out-soft), background 0.2s;
		box-shadow: var(--shadow-1);
	}
	.tg.on .knob {
		transform: translateX(20px);
		background: var(--accent-ink);
	}
</style>
