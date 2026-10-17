<script module lang="ts">
	/** What the turn is doing right now, from the stream's `status` events. */
	export type Progress = {
		state: string; // queued | loading | thinking | searching | tool | reading | writing
		label: string;
		eta_ms?: number; // only sent when the device's own measured speed makes it honest
		at: number; // when this status arrived (ms)
		started: number; // when the turn started (ms)
		stages: string[]; // every state seen so far, in order
	};
</script>

<script lang="ts">
	import { Check } from '@lucide/svelte';
	import { t } from '$lib/i18n/index.svelte';

	let { progress, compact = false }: { progress: Progress; compact?: boolean } = $props();

	let now = $state(Date.now());
	$effect(() => {
		const timer = setInterval(() => (now = Date.now()), 500);
		return () => clearInterval(timer);
	});

	// Search → Read → Write. Labels are getters so they follow the interface language.
	const STEPS = [
		{ id: 'searching', get label() { return t('chat.stepSearch'); } },
		{ id: 'reading', get label() { return t('chat.stepRead'); } },
		{ id: 'writing', get label() { return t('chat.stepWrite'); } }
	];
	const elapsed = $derived(Math.max(0, Math.floor((now - progress.started) / 1000)));
	const grounded = $derived(progress.stages.includes('searching'));
	const current = $derived(STEPS.findIndex((s) => s.id === progress.state));
	const left = $derived(progress.state === 'reading' && progress.eta_ms ? Math.round((progress.eta_ms - (now - progress.at)) / 1000) : 0);

	function fmt(s: number) {
		return s < 60 ? t('chat.seconds', { n: s }) : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
	}
	function stepState(i: number) {
		if (i === current) return 'now';
		if (current < 0) return progress.stages.includes(STEPS[i].id) ? 'done' : 'todo';
		return i < current ? 'done' : 'todo';
	}
</script>

{#if compact}
	<div class="tp compact">
		<span class="pulse" aria-hidden="true"></span>
		<span>{progress.state === 'writing' ? t('chat.writing') : progress.label.replace(/…$/, '')}</span>
		{#if elapsed >= 1}<span class="time">· {fmt(elapsed)}</span>{/if}
	</div>
{:else}
	<div class="tp">
		{#if grounded}
			<ol class="steps" aria-hidden="true">
				{#each STEPS as s, i (s.id)}
					{@const st = stepState(i)}
					<li class={st}>
						<span class="mark">{#if st === 'done'}<Check size={10} strokeWidth={3} />{/if}</span>{s.label}
					</li>
				{/each}
			</ol>
		{/if}
		<div class="line">
			<span class="tp-label">{progress.label}</span>
			<span class="time">
				{#if elapsed >= 1}{fmt(elapsed)}{/if}{#if left > 1}<span class="eta">{elapsed >= 1 ? ' · ' : ''}{t('chat.secondsLeft', { n: left })}</span>{/if}
			</span>
		</div>
	</div>
{/if}

<style>
	.tp {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 2px 0 4px;
	}
	.steps {
		display: flex;
		align-items: center;
		gap: 6px;
		list-style: none;
		margin: 0;
		padding: 0;
		font-size: 0.72rem;
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--text-3);
	}
	.steps li {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.steps li + li::before {
		content: '';
		width: 18px;
		height: 1px;
		background: var(--line-2);
		margin-right: 2px;
	}
	.mark {
		width: 14px;
		height: 14px;
		border-radius: 50%;
		display: grid;
		place-items: center;
		border: 1.5px solid var(--line-2);
		flex: none;
	}
	.steps li.done {
		color: var(--text-2);
	}
	.steps li.done .mark {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
	.steps li.now {
		color: var(--accent);
	}
	.steps li.now .mark {
		border-color: var(--accent);
		box-shadow: 0 0 0 3px var(--accent-soft);
		animation: ring 1.6s ease-in-out infinite;
	}
	@keyframes ring {
		50% {
			box-shadow: 0 0 0 5px transparent;
		}
	}
	.line {
		display: flex;
		align-items: baseline;
		flex-wrap: wrap;
		gap: 4px 10px;
	}
	.tp-label {
		font-size: 0.95rem;
		background: linear-gradient(90deg, var(--text-3) 0%, var(--text) 40%, var(--text-3) 80%);
		background-size: 200% 100%;
		-webkit-background-clip: text;
		background-clip: text;
		color: transparent;
		animation: sweep 1.8s linear infinite;
		overflow-wrap: anywhere;
	}
	@keyframes sweep {
		to {
			background-position: -200% 0;
		}
	}
	.time {
		font-size: 0.78rem;
		color: var(--text-3);
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	.compact {
		flex-direction: row;
		align-items: center;
		gap: 6px;
		margin-top: 8px;
		padding: 0;
		font-size: 0.76rem;
		color: var(--text-3);
	}
	.pulse {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--accent);
		animation: blink 1.2s ease-in-out infinite;
	}
	@keyframes blink {
		50% {
			opacity: 0.3;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.tp-label,
		.pulse,
		.steps li.now .mark {
			animation: none;
		}
		.tp-label {
			color: var(--text-2);
			background: none;
		}
	}
	:global([data-motion='reduced']) .tp-label,
	:global([data-motion='reduced']) .pulse,
	:global([data-motion='reduced']) .steps li.now .mark {
		animation: none;
	}
	:global([data-motion='reduced']) .tp-label {
		color: var(--text-2);
		background: none;
	}
</style>
