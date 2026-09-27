<script lang="ts">
	let { value, options, onchange, disabled = false }: { value: string; options: [string, string][]; onchange: (v: string) => void; disabled?: boolean } = $props();
</script>

<div class="seg" role="radiogroup">
	{#each options as [v, label] (v)}
		<button role="radio" aria-checked={value === v} class:on={value === v} {disabled} onclick={() => onchange(v)}>{label}</button>
	{/each}
</div>

<style>
	.seg {
		display: inline-flex;
		padding: 3px;
		border-radius: 999px;
		background: var(--surface-2);
		border: 1px solid var(--line);
		flex-wrap: wrap;
	}
	button {
		height: 32px;
		padding: 0 14px;
		border-radius: 999px;
		font-size: 0.84rem;
		font-weight: 550;
		color: var(--text-2);
		transition: background 0.18s, color 0.18s;
	}
	button:hover {
		color: var(--text);
	}
	button.on {
		background: var(--surface-3);
		color: var(--text);
		box-shadow: inset 0 0 0 1px var(--line-2);
	}
	button:disabled {
		opacity: 0.5;
	}
</style>
